from SCons.Script import *
import sys
import os
from os.path import join
import re

'''
Copyright (c) 2015, Dan Newman <dan.newman@mtbaldy.us>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---------

The following Scons arduino tool is loosely based upon the earlier work
of github user tomjnixon and his arduino-scons-alt repository.   In August
2015, I found his work which hadn't been updated since 2013 and which (1)
only ever worked for AVRs, (2) had never been updated to Arduino app versions
later than 1.0, and (3) didn't prevent scons from leaving object files in
the Arduino application directory tree.

What appears below has been updated for Arduino 1.5 and later and, using
a sleazy symlink trick, prevents object files from being left in the Arduino
application tree.

NOTE: VariantDir() and Repository() cannot be used effectively with an
      Arduino distribution without a little trickery.

1. VariantDir() requires that the source files live in or below the main
   source tree.  So, to use just VariantDir() the Arduino library sources
   would need to be copied into the source tree.

2. Repository() allows files outside the source tree to be referenced, but
   when combined with VariantDir() requires identical directory naming
   between the "mounted" repository and the VariantDir() directory.
   Consider, for example,

       source directory = src
       build variant directory = build/uno
       arduino source = /usr/local/arduino/hardware/arduino/avr

   With the commands

       VariantDir("build/uno")
       Repository("/usr/local/arduino/hardware/arduino/avr")

   there is now a problem.  When scons looks for Arduino library
   sources to build, it will require them to be under

       /usr/local/arduino/hardware/arduino/avr/build/uno

   This can be dealt with by making a sym link loop from uno/ -> avr/
   but that may cause problems for unsuspecting programs.  Alternatively,
   we can

       ln -s /usr/local/arduino/hardware/arduino \
             /usr/local/arduino/hardware/build \
       ln -s /usr/local/arduino/hardware/arduino/avr \
             /usr/local/arduino/hardware/arduino/uno \

   Thus, when told to build cores/arduino/*.cpp (core library) or
   libraries/SPI/*.cpp (SPI library), scons will find them under
   build/uno/cores/arduino and build/uno/libraries/SPI.

   This tool uses this latter sym linking approach.  It's admittedly
   sleazy -- it puts sym links into the Arduino tree -- but there's
   presently no better alternatives.
'''

def exists(env):
    return 1

def generate(env):
    original_env = env

    '''
    Parse information from an arduino board or platform file and
    stuff it into a dictionary.

    When select_key is None, then every non-comment line is stuffed
    into the dictionary.  When select_key is a string, then only
    entries beginning with that key,

        key.subkey = value

    are used.  They will be placed into the dictionary using subkey
    as the dictionary key.
    '''

    def read_arduino_file(f, select_key=None, tab={}):

        # We return True if we find select_key or if select_key is None
        if select_key is None:
            key_seen = True
        else:
            key_seen = False

        # Read the file line by line
        for line in f:
            if line.strip() and line.strip()[0] != "#":
                lhs, rhs = line.strip().split("=", 1)
                if select_key is None:
                    tab[lhs] = rhs
                else:
                    tup = tuple(lhs.split("."))
                    if ( len(tup) > 1 ) and ( select_key == tup[0] ):
                        key_seen = True
                        tup = tup[1:]
                        tab['.'.join([w for w in tup])] = rhs

        return key_seen, tab


    '''
    Go through each table value and, if it contains an occurrence of the
    string

        '{' opt '}'

    replace it (and the curly braces) with the value of the string val.
    '''

    def substitute(opt, val, tab):

        if opt is None:
            return False

        if val is None:
            val = ''

        # If the value needs a substitution then skip for now
        if val.find('{') >= 0:
            return False

        if opt[0] != '{':
            opt = '{' + opt + '}'

        changed = False

        for key in tab:
            if tab[key].find(opt) >= 0:
                tab[key] = tab[key].replace(opt, val)
                changed = True

        return changed


    '''
    Undergo a single pass through the dictionary tab, taking
    each key/value pair,

        tab[key] = value

    and seeing if they can be used for string substitutions.
    That is, if the string value does not itself contain any
    curly braces, then see if other table entries contain
    the substring

        '{' key '}'

    If they do, then replace '{' key '}' with value.
    '''

    def mungTable_inner(tab):

        if tab is None:
            return False

        changed = False
        for key in tab:
            if tab[key].find('{') < 0:
                changed = changed or substitute(key, tab[key], tab)

        return changed


    '''
    Iteratively perform table string substitutions until no further
    substitutions can be done.
    '''

    def mungTable(tab):
        changed = mungTable_inner(tab)
        while changed:
            changed = mungTable_inner(tab)

    def clean_flags(flags_str, replace_list=None, drop_list=None):

        if flags_str is None:
            return ''

        if drop_list is None:
            drop_list = []

        if replace_list is None:
            replace_list = []

        # Cannot split within quoted strings....
        flags = [p for p in re.split("( |\\\".*?\\\"|'.*?')", flags_str) if p.strip()]

        new_flags = []
        skip_next = 0

        for token in flags:

            if skip_next > 0:
                skip_next = skip_next - 1
                continue

            # Remove leading and trailing white space
            # Skip if token reduced to the empty string
            token = token.strip()
            if len(token) == 0:
                continue

            # See if the token is in the list of items to drop
            found = False
            for drop in drop_list:
                if token == drop[0]:
                    # Number of following tokens to drop
                    skip_next = drop[1]
                    found = True
                    break
            if found:
                continue

            # See if the token is in the list of items to replace
            replaced = False
            for replace in replace_list:
                if token == replace[0]:
                    new_flags.append(replace[1])
                    replaced = True
                    break
            if replaced:
                continue

            # Tokens starting with " and not "-I" should be dropped
            if token[0] == '"' and token[1] != '-':
                continue

            # And dop tokens starting with { as well
            elif token[0] == '{':
                continue

            # keep the token
            token2 = re.sub(r'=\"(.*\s.*)\"$', r'=\\"\1\\"', token.strip("'"))
            new_flags.append(token2)

        return new_flags

    def setInfo(info, new, old):
        if old in info:
            info[new] = info[old]
            return True
        else:
            return False

    @env.AddMethod
    def CleanupBoard(env, version, arch, board):

        variant_dir = env.subst('$VARIANT_DIR')
        build_dir, platform_dir = os.path.split(variant_dir)
        if platform_dir == '':
            return

        if type(version) is str:
            version = int(version)

        if (arch != 'avr') and (version >= 160):
            hardware_path = join(env.subst('$ARDUINO_HOME'), 'hardware')
            arduino_path  = join(hardware_path, arch.lower())
        elif version >= 150:
            hardware_path = join(env.subst('$ARDUINO_HOME'), 'hardware')
            arduino_path  = join(hardware_path, 'arduino')
        else:
            raise Exception('Unsupported Arduino version')

        if build_dir != '':
            if os.path.islink(join(hardware_path, build_dir)):
                os.unlink(join(hardware_path, build_dir))

        if os.path.islink(join(arduino_path, platform_dir)):
            os.unlink(join(arduino_path, platform_dir))


    @env.AddMethod
    def ConfigureBoard(env, version, arch, board, options=None):

        '''
        Configure this environment for the given board name. Available boards
        are listed in $ARDUINO_HOME/hardware/arduino/$ARDUINO_ARCH/boards.txt
        '''

        env.SetDefault(
            ARDUINO_HOME = os.environ.get("ARDUINO_HOME", "/usr/share/arduino"))
        env.SetDefault(
            ARDUINO_ARCH = os.environ.get("ARDUINO_ARCH", "sam"))
        env.SetDefault(
            BOSSAC_PATH = os.environ.get('BOSSAC_PATH', ''))

        arch = arch.lower()

        if type(version) is str:
            version = int(version)

        version_path = '%d.%d.%d' % (version / 100, (version % 100) / 10, version % 10)
        if (arch != 'avr') and (version >= 160):
            hardware_path = join(env.subst('$ARDUINO_HOME'), 'hardware')
            arduino_path  = join(hardware_path, arch)
            arch_path     = join(arduino_path, version_path)
        elif version >= 150:
            hardware_path = join(env.subst('$ARDUINO_HOME'), 'hardware')
            arduino_path  = join(hardware_path, 'arduino')
            arch_path     = join(arduino_path, arch)
        else:
            raise Exception('Unsupported Arduino version')

        variant_dir = env.subst('$VARIANT_DIR')

        # split('')    --> '', ''
        # split('a')   --> '', 'a'
        # split('a/b') --> 'a', 'b'

        build_dir, platform_dir = os.path.split(variant_dir)
        if platform_dir != '':

            env.CleanupBoard(version, arch, board)

            if build_dir != '':
                # Two levels of sym links needed
                os.symlink(arduino_path, join(hardware_path, build_dir))
                os.symlink(arch_path, join(arduino_path, platform_dir))
            else:
                # One level of sym links needed
                os.symlink(arch_path, join(arduino_path, platform_dir))

        # Repository() so that we do not drop .o files in the actual Arduino app directories
        Repository(hardware_path)

        # Read the boards.txt and platform.txt files
        try:
            with open(join(arch_path, 'boards.txt')) as f:
                okay, info = read_arduino_file(f, board)
                if not okay:
                    raise Exception(env.subst(board + " is not a recognized Arduino board"))
            with open(join(arch_path, 'platform.txt')) as f:
                okay, info = read_arduino_file(f, None, info)
        except IOError, e:
            raise Exception(env.subst(
                "ARDUINO_HOME ($ARDUINO_HOME) is not a valid arduino installation."))

        # Push into info[] some values useful for substitutions
        info['compiler.warning.flags'] = ''
        info['build.arch'] = arch.upper()
        info['build.arch.path'] = arch.lower()

        if (arch != 'avr') and (version >= 160):
            if not ('ARDUINO_TOOLS' in os.environ):
                raise Exception('ARDUINO_TOOLS not defined in environment')
            info['runtime.tools.arm-none-eabi-gcc.path'] = os.environ['ARDUINO_TOOLS']
            info['build.system.path'] = '$ARDUINO_HOME/hardware/' + \
                '{build.arch.path}/' + version_path + '/system'
            info['build.variant.path'] = '$ARDUINO_HOME/hardware/' + \
                '{build.arch.path}/' + version_path + \
                '/variants/{build.variant}'
        else:
            if arch == 'avr':
                info['runtime.tools.avr-gcc.path'] = '$ARDUINO_HOME/' + \
                    'hardware/tools/' + arch
            info['build.system.path'] = '$ARDUINO_HOME/hardware/arduino/' + \
                '{build.arch.path}/system'
            info['build.variant.path'] = '$ARDUINO_HOME/hardware/arduino/' + \
                '{build.arch.path}/variants/{build.variant}'
            info['runtime.ide.path'] = '$ARDUINO_HOME'
            if 'version' in info:
                info['runtime.ide.version'] = info['version'].replace('.','')

        # Info for bosac/avrdude command
        if arch == 'avr':
            prog = 'avrdude'
        else:
            prog = 'bossac'

        # Lovely thing is that the platform.txt entries for programming
        # sam vs. avr are completely different...

        ops = sys.platform.lower()

        if (ops == 'win32'):
            setInfo(info, 'cmd', 'tools.' + prog + '.cmd.windows')
        if not ('cmd' in info):
            setInfo(info, 'cmd', 'tools.' + prog + '.cmd')

        setInfo(info, 'cmd.path', 'tools.' + prog + '.cmd.path')
        setInfo(info, 'config.path', 'tools.' + prog + '.config.path')
        if not setInfo(info, 'path', 'tools.' + prog + '.path'):
            info['path'] = join(env.subst('$ARDUINO_HOME', 'hardware', 'tools'))

        # Needed for Arduino 1.6
        if not ('runtime.tools.bossac.path' in info):
            info['runtime.tools.bossac.path'] = env.subst('$BOSSAC_PATH')

        if not setInfo(info, 'upload.verbose', 
                       'tools.' + prog + '.upload.params.quiet'):
            info['upload.verbose'] = ''

        info['upload.native_usb'] = '$NATIVE'
        info['serial.port.file'] = '$PORT'

        # Now process all the substitution strings in the table
        mungTable(info)

        # Options?
        # If options were specified, then attempt to set CFLAGS and CXXFLAGS
        # using information from the Arduino platform.txt file

        if not (options is None):

            if 'recipe.c.o.pattern' in info:

                if 'cc_flags_drop_list' in options:
                    drop_list = options['cc_flags_drop_list']
                else:
                    drop_list = None
                if 'cc_flags_replace_list' in options:
                    replace_list = options['cc_flags_replace_list']
                else:
                    replace_list = None

                cc_flags = clean_flags(info['recipe.c.o.pattern'],
                                       replace_list, drop_list)
                if 'build.usb_flags' in info:
                    if info['build.usb_flags'].find('{') < 0:
                        cc_flags += clean_flags(info['build.usb_flags'],
                                                replace_list, drop_list)

                env.Replace(CFLAGS = cc_flags)

            if 'recipe.cpp.o.pattern' in info:

                if 'cxx_flags_drop_list' in options:
                    drop_list = options['cxx_flags_drop_list']
                else:
                    drop_list = None
                if 'cxx_flags_replace_list' in options:
                    replace_list = options['cxx_flags_replace_list']
                else:
                    replace_list = None

                cxx_flags = clean_flags(info['recipe.cpp.o.pattern'],
                                        replace_list, drop_list)
                if 'build.usb_flags' in info:
                    if info['build.usb_flags'].find('{') < 0:
                        cxx_flags += clean_flags(info['build.usb_flags'],
                                                 replace_list, drop_list)

                env.Replace(CXXFLAGS = cxx_flags)

        # Generic info we can always set for the compiles
        # Must set -O2; otherwise, we get a link time warning about
        # libarduino-core.a(UARTClass.o): In function `HardwareSerial::HardwareSerial()':
        # .../cores/arduino/HardwareSerial.h:26: warning: undefined reference to `vtable for HardwareSerial'

        if arch == 'avr':
            env.Append(CXXFLAGS = [ '-std=gnu++11' ],
                       CFLAGS   = [ '-std=gnu99' ] )
        else:
            env.Append(CXXFLAGS = [ '-O2', '-Wall', '-std=gnu++11', '-D__SAM3X8E__', '-mthumb' ],
                       CFLAGS   = [ '-O2', '-Wall', '-std=gnu99', '-D__SAM3X8E__', '-mthumb' ] )

        # Sensible defaults for variables that aren't defined by default.

        if 'build.vid' in info:
            vid = info['build.vid']
        elif 'vid' in info:
            vid = info['vid']
        elif 'vid.0' in info:
            vid = info['vid.0']
        else:
            vid = None

        if 'build.pid' in info:
            pid = info['build.pid']
        elif 'pid' in info:
            pid = info['pid']
        elif 'pid.0' in info:
            pid = info['pid.0']
        else:
            pid = None

        if not (vid is None):
            env.SetDefault( USB_VID = vid )
        if not (pid is None):
            env.SetDefault( USB_PID = pid )

        if 'build.variant_system_lib' in info:
            env.SetDefault( VARIANT_SYSLIB = info['build.variant_system_lib'] )

        env.SetDefault(
            BOARD        = board,
            BOARD_NAME   = info['build.board'],
            VERSION      = '%d' % version,
            VERSION_PATH = version_path,
            ARCH         = arch,
            F_CPU        = info['build.f_cpu'],
            M_CPU        = info['build.mcu'],
            VARIANT      = info['build.variant'],
            CORE         = info['build.core'],
            BUILD_DIR    = join(build_dir, '$BOARD') )

        if (arch != 'avr') and (version >= 160):
            env.SetDefault(
                VARIANT_PATH = join('$ARDUINO_HOME', 'hardware',
                                    '$ARDUINO_ARCH', version_path,
                                    'variants', '$VARIANT'),
                CORE_DIR    = join('$ARDUINO_HOME', 'hardware', '$ARDUINO_ARCH',
                                   version_path) )
            env.Append( CPPPATH = [
                    join('$ARDUINO_HOME', 'hardware', '$ARDUINO_ARCH',
                         version_path, 'cores', 'arduino'),
                    join('$ARDUINO_HOME', 'hardware', '$ARDUINO_ARCH',
                         version_path, 'cores', 'arduino', 'avr'),
                    join('$ARDUINO_HOME', 'hardware', '$ARDUINO_ARCH',
                         version_path, 'cores', 'arduino', 'USB'),
                    info['build.variant.path'] ] )
        else:
            env.SetDefault(
                VARIANT_PATH = join('$ARDUINO_HOME', 'hardware', 'arduino',
                                    '$ARDUINO_ARCH', 'variants', '$VARIANT'),
                CORE_DIR     = join('$ARDUINO_HOME', 'hardware', 'arduino',
                                   '$ARDUINO_ARCH') )
            if 'build.variant_system_lib' in info:
                env.SetDefault(
                    VARIANT_SYSLIB = info['build.variant_system_lib'])
            env.Append( CPPPATH = [
                    join('$ARDUINO_HOME', 'hardware', 'arduino',
                         '$ARDUINO_ARCH','cores', 'arduino'),
                    join('$ARDUINO_HOME', 'hardware', 'arduino',
                         '$ARDUINO_ARCH', 'cores', 'arduino', 'avr'),
                    join('$ARDUINO_HOME', 'hardware', 'arduino',
                         '$ARDUINO_ARCH', 'cores', 'arduino', 'USB'),
                    info['build.variant.path'] ] )

        # Set binaries to use
        if 'compiler.path' in info:
            cpath = info['compiler.path']
        else:
            cpath = ''

        if arch == 'avr':
            env.Replace(RANLIB = join(cpath, 'avr-ranlib'))
        elif arch == 'sam':
            env.Replace(RANLIB = join(cpath, 'arm-none-eabi-ranlib'))
        else:
            raise Exception('Unsupported architecture, ' + arch)

        if 'compiler.c.cmd' in info:
            env.Replace(CC = join(cpath, info['compiler.c.cmd']))
            if arch == 'avr':
                env.Replace(AS = join(cpath, info['compiler.c.cmd']))

        if 'compiler.cpp.cmd' in info:
            env.Replace(CXX = join(cpath, info['compiler.cpp.cmd']))

        if 'compiler.ar.cmd' in info:
            env.Replace(AR = join(cpath, info['compiler.ar.cmd']))

        if 'compiler.ar.flags' in info:
            env.Replace(ARFLAGS = info['compiler.ar.flags'])

        if 'compiler.S.flags' in info:
            env.Replace(ASFLAGS = info['compiler.S.flags'])

        if 'compiler.size.cmd' in info:
            env.Replace(SIZE = join(cpath, info['compiler.size.cmd']))

        if 'compiler.objcopy.cmd' in info:
            env.Replace(OBJCOPY = join(cpath, info['compiler.objcopy.cmd']))

        if 'compiler.c.elf.cmd' in info:
            env.Replace(ELF = join(cpath, info['compiler.c.elf.cmd']),
                        LD  = join(cpath, info['compiler.c.elf.cmd']))

        if 'recipe.c.combine.pattern' in info:

            if 'map_name' in env:
                map_name = env['map_name']
            else:
                map_name = 'RepRapFirmware.map'

            if 'VARIANT_DIR' in os.environ:
                map_name = join(os.environ['VARIANT_DIR'], map_name)

            s = info['recipe.c.combine.pattern']
            s = s.replace('{build.path}/{build.project_name}.map', map_name)
            s = s.replace('"{build.path}/{build.project_name}.elf"', '$TARGET')
            s = s.replace('{build.path}/{build.project_name}.elf',   '$TARGET')
            s = s.replace('"-L{build.path}"', '$_LIBDIRFLAGS')
            s = s.replace('-L{build.path}',   '$_LIBDIRFLAGS')
            s = s.replace('"{build.path}/syscalls_sam3.c.o"',
                          join(env.subst('$VARIANT_DIR'), 'cores',
                               'arduino', 'syscalls_sam3.o') + ' $_LIBFLAGS')
            s = s.replace('{build.path}/syscalls_sam3.c.o',
                          join(env.subst('$VARIANT_DIR'), 'cores',
                               'arduino', 'syscalls_sam3.o') + ' $_LIBFLAGS')

            # Added for 1.6.5 SAM libraries (appeared in Arduino 1.6.6)
            s = s.replace('"{build.path}/core/syscalls_sam3.c.o"',
                          join(env.subst('$VARIANT_DIR'), 'cores',
                               'arduino', 'syscalls_sam3.o') + ' $_LIBFLAGS')
            s = s.replace('{build.path}/core/syscalls_sam3.c.o',
                          join(env.subst('$VARIANT_DIR'), 'cores',
                               'arduino', 'syscalls_sam3.o') + ' $_LIBFLAGS')

            s = s.replace('"{object_files}"', '$SOURCES')
            s = s.replace('{object_files}', '$SOURCES')
            s = s.replace('"{build.path}/{archive_file}"', '')
            s = s.replace('{build.path}/{archive_file}', '')
            env.Append( BUILDERS = { 'Elf' : Builder(action=s) } )

        if (arch != 'avr') and (version >= 160):
            pattern = 'recipe.objcopy.bin.pattern'
        else:
            pattern = 'recipe.objcopy.hex.pattern'

        if pattern in info:

            s = info[pattern]
            s = s.replace('"{build.path}/{build.project_name}.elf"', '$SOURCES')
            s = s.replace('{build.path}/{build.project_name}.elf',   '$SOURCES')
            s = s.replace('"{build.path}/{build.project_name}.bin"', '$TARGET')
            s = s.replace('{build.path}/{build.project_name}.bin',   '$TARGET')
            s = s.replace('"{build.path}/{build.project_name}.hex"', '$TARGET')
            s = s.replace('{build.path}/{build.project_name}.hex',   '$TARGET')
            env.Append( BUILDERS = { 'Hex' : Builder(action=s, suffix='.hex', src_suffix='.elf') } )

        if 'recipe.S.o.pattern' in info:
            s = info['recipe.S.o.pattern']
            s = s.replace('"{includes}"',    '$_CPPINCFLAGS')
            s = s.replace('{includes}',      '$_CPPINCFLAGS')
            s = s.replace('"{source_file}"', '$SOURCES')
            s = s.replace('{source_file}',   '$SOURCES')
            s = s.replace('"{object_file}"', '$TARGET')
            s = s.replace('{object_file}',   '$TARGET')
            s = s.replace('"{build.path}/{archive_file}"', '')
            s = s.replace('{build.path}/{archive_file}', '')
            env.Replace( ASCOM = s, ASPPCOM = s )

        pattern = 'tools.' + prog + '.upload.pattern'
        if pattern in info:

            s = info[pattern]
            s = s.replace('"{build.path}/{build.project_name}.bin"', '$SOURCES')
            s = s.replace('{build.path}/{build.project_name}.bin',   '$SOURCES')
            env.Replace( UPLOAD = s )

        return env

    @env.AddMethod
    def ArduinoCore(env):
        '''
        Build the arduino core library
        '''
        version = int(env.subst('$VERSION'))
        arch = env.subst('$ARDUINO_ARCH').lower()
        if (arch != 'avr') and (version >= 160):
            env.Append ( CPPPATH = [ join('$ARDUINO_HOME', 'hardware',
                                          '$ARDUINO_ARCH', '$VERSION_PATH',
                                          'system', 'libsam', 'include') ] )
        else:
            env.Append ( CPPPATH = [ join('$ARDUINO_HOME', 'hardware',
                                          'arduino', '$ARDUINO_ARCH',
                                          'system', 'libsam', 'include') ] )
        if arch == 'avr':

            # Arduino AVR core library has two identically named source files,
            #   wiring_pulse.c
            #   wiring_pulse.S
            # This causes grief as normally scons wants to call the objects
            # wiring_pulse.o and wiring_pulse.o.  So, we need to address that...

            c_objs = env.Object(cfiles(env, 'cores/$CORE'))
            asm_objs = env.Object(source='cores/$CORE/wiring_pulse.S',
                                  target='cores/$CORE/wiring_pulse.S.o')
            return env.Clone().Library("arduino-core", [ c_objs, asm_objs ])

        else:

            srcfiles = cfiles(env, 'cores/$CORE') + \
                cfiles(env, 'cores/$CORE/avr') + \
                cfiles(env, 'cores/$CORE/USB') + \
                cfiles(env, 'variants/$VARIANT')
            return env.Clone().Library("arduino-core", srcfiles)

    def cfiles(env, path):
        '''
        Identify source files, .c, .cpp, and .S
        '''
        return env.Glob(join(path, '*.c')) + env.Glob(join(path, '*.cpp'))

    @env.AddMethod
    def ArduinoLibrary(env, name, path=None):
        '''
        Build a library. If path is not given, it is assumed to be a builtin
        arduino library. This adds the path to the inclide path, and builds
        all .c and .cpp files from path and path/utility into a library.
        '''
        full_name = join('$BUILD_DIR', 'libraries', name)
        path = path or join('libraries', name)
        version = int(env.subst('$VERSION'))
        arch = env.subst('$ARDUINO_ARCH').lower()
        if (arch != 'avr') and (version >= 160):
            env.Append(CPPPATH = [ join('$ARDUINO_HOME', 'hardware',
                                        '$ARDUINO_ARCH', '$VERSION_PATH',
                                        path) ] )            
        else:
            env.Append(CPPPATH = [ join('$ARDUINO_HOME', 'hardware', 'arduino',
                                        '$ARDUINO_ARCH', path) ] )
            if name == 'Wire':
                env.Append(CPPPATH = [ join('$ARDUINO_HOME', 'hardware',
                                            'arduino', '$ARDUINO_ARCH',
                                            path, 'utility') ] )
        sources = cfiles(env, path)
        if (name == 'Wire') and (arch == 'avr'):
            sources += cfiles(env, join(path, 'utility'))
        return env.Clone().Library(path, sources)

    @env.AddMethod
    def Sketch(env, name, sources):
        '''
        Build a program from sources, and copy the resulting elf file into a hex
        file for uploading.
        '''
        elf = env.Program(name, sources, PROGSUFFIX = '.elf')
        return env.Hex(name, elf)

    @env.AddMethod
    def Upload(env, source, name="upload"):

        def tickle(target, source, env):
            import serial
            import time

            port = env['PORT']
            print 'Tickling the bootloader via port ' + port
            try:
                with serial.Serial(port, baudrate=1200) as sd:
                    sd.setDTR(1)
                    time.sleep(0.5)
                    sd.setDTR(0)
            except serial.SerialException, e:
                return str(e)

        if 'NATIVE' in env:
            native = env['NATIVE'].lower()
        else:
            native = 'true'

        cmd = env['UPLOAD']
        cmd = cmd.replace('$NATIVE', native)
        cmd = cmd.replace('$PORT', env['PORT'].replace('/dev/', ''))
        target = env.Alias(name, source, [tickle, cmd])
        AlwaysBuild(target)
        return target
