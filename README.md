## Scons tools for Arduino AVR and SAM/ARM projects

## Introduction

The Scons arduino tool `arduino.py` is loosely based upon the earlier
work of github user tomjnixon and his arduino-scons-alt repository.   In
August 2015, I found his work which hadn't been updated since 2013 and which
(1) only ever worked for AVRs, (2) had never been updated to Arduino app
versions later than 1.0, and (3) didn't prevent scons from leaving object
files in the Arduino application directory tree.

`arduino.py` has been tested with Arduino 1.5 and 1.6 for both AVR and SAM/ARM
architectures.  To prevent object files from being left in the Arduino
application's directory tree, a sleazy symlink trick is used owing to
the restrictive behavior of scons' `Repository()` facility.

1. `VariantDir()` requires that the source files live in or below the main
   source tree.  So, to use just `VariantDir()` the Arduino library sources
   need to be copied into the source tree so as to provide visibility to
   a scons build.

2. `Repository()` makes sources outside the source tree visible for
   building without leaving object files in that outside source tree.
   But, when combined with `VariantDir()` requires identical directory
   naming between the "mounted" repository and the `VariantDir()`
   directory.  Consider, for example,

       source directory = src/
       build variant directory = BUILD/UNO/
       Arduino source directory = /usr/local/arduino/hardware/arduino/avr/

   With the commands

       VariantDir('BUILD/UNO', 'src')
       Repository('/usr/local/arduino/hardware/arduino/avr')

   there is now a problem.  When scons looks for Arduino library
   sources to build, it will require them to be under

       /usr/local/arduino/hardware/arduino/avr/BUILD/UNO/

   This can be dealt with by making a symbolic link loop from `UNO/` to
   `avr/` but that may cause problems with unsuspecting programs.
   Alternatively, we can

       ln -s /usr/local/arduino/hardware/arduino \
             /usr/local/arduino/hardware/BUILD \
       ln -s /usr/local/arduino/hardware/arduino/avr \
             /usr/local/arduino/hardware/arduino/UNO \

   Thus, when told to build `cores/arduino/*.cpp` (core library) or
   `libraries/SPI/*.cpp` (SPI library), scons will find them under
   `BUILD/UNO/cores/arduino` and `BUILD/UNO/libraries/SPI`.

   This tool uses this latter symbolic link approach.  It's admittedly
   sleazy -- it puts sym links into the Arduino tree -- but there's
   presently no better alternatives.  The links are automatically
   established; you do not need to manually create them.  This method
   can be used with
   
   * No `VariantDir()`,
   * `VariantDir('a', )`, and
   * `VariantDir('a/b', )`
   
   That is, this code works with no variant directory, a single-directory
   level variant directory, and a two-directory level variant directory.

   
## Usage
   
Copy the `arduino.py` file to your project.  It can be kept tucked
away in a subdirectory.  Scons also has methods for installing it in
site-wide or per-user scons "tool" directories.  The examples
provided here keep it in a subdirectory named `scons_tools` and
provide that directory's name and location with the `Environment()` call.
   
In you SConstruct file, set into `os.environment()`
   
1. The Arduino application version as an single integer (e.g., for
   1.5.8beta, use "158"; for 1.6.5, use "165").
   
        os.environ['ARDUINO_VERSION'] = '158'

2. The path to the directory containing the Arduino application's
   `hardware` folder,

        os.environ['ARDUINO_HOME'] = '/usr/local/arduino'

   Note this is not the path for the `hardware` folder itself: it is
   the path to the folder containing the `hardware` folder.

3. For ARM/SAM architectures and Ardiuno 1.6 or later, the path
   to the directory tree in which the separately installed gcc
   toolchain is located.  E.g.,

        os.environ['ARDUINO_TOOLS'] = '/Users/dnewman/Library/Arduino15/packages/arduino/tools/arm-none-eabi-gcc/4.8.3-2014q1'

See the example `SConstruct` files for working examples of effecting
the above three settings.

When creating the scons environment, declare usage of the tool `arduino`
and the location of the directory containing `arduino.py`.  For example,

    env = Environment(tools = ['default', 'arduino'],
                      toolpath = ['scons_tools'] )

To then load information about the target Arduino board, issue the
command

    env.ConfigureBoard(arduino_version, arduino_arch, board, options)

where

1. `arduino_version` is an actual integer (not a string) representing
   the Arduino version number (e.g., 158, 165, etc.).

2. `arduino_arch` is the string `'avr'` or `'sam'` and represents
   the target architecture.  Yes, this could be derived from `board` but
   that would require either maintaining a table or making guesses in order
   to find the correct `boards.txt` file.  (The location of `boards.txt`
   is dependent on both the target architecture and the version of the
   Arduino application.)

3. `board` is the Arduino board name as it appears in the architecture's
   `boards.txt` (e.g., "uno", "arduino_due_x").

4. `options` is used to control how the Arduino `platform.txt` compile
   recipes are transformed into CC and C++ commands for use with scons.
   The Arduino recipes have undesirable (dubious) settings such as `-w`
   which disables **all** compiler warnings.  These options may be used
   to drop (strip) or replace portions of the recipes

   `options` is a dictionary containing any or all of the following keys
    
    * `cc_flags_drop_list` -- strings to drop from CC commands
    * `cc_flags_replace_list` -- strings to replace in CC commands
    * `cxx_flags_drop_list` -- strings to drop from C++ (CXX) commands
    * `cxx_flags_replace_list` -- strings to replace in C++ (CXX) commands
    
    A replace list is a list of 2-tuples, each 2-tuple containing two
    strings: a substring to look for and a substring to replace it with.
    E.g., to replace `-w` with `-Wall` and `-Os` with `-O2`, use

       [ ('-w', '-Wall'), ('-Os', '-O2') ] 
    
    Note that depending upon a replace list may cause problems after
    upgrading the Arduino application: a new Arduino `platform.txt` file
    may no longer specify a given switch.  With the above example, if
    you need `-O2` specified but `-Os` is no longer used in the new
    `platform.txt`, then the replacement will not occur and thus `-O2`
    will not be asserted.  It is safer to strip unwanted flags/switches
    with a drop list and use `env.Append()` to add assert necessary 
    flags or switches for `CCFLAGS` or `CXXFLAGS`.
    
    A drop list is a list of 2-tuples, each 2-tuple containing a string
    to drop and a count of the subsequent number of tokens following the
    string to also drop. E.g., the drop list
    
       [ ('-o', 1) ]
    
    drops the `-o` switch and the single argument immediately following it.
    The following drops both `-o` and `-w`,
    
       [ ('-o', 1), ('-w', 0) ]
       

## Examples

Two complete examples are provided.  After editing their `SConstruct`
files to have Arduino version and path information specific to your
computer, they should build with a simple scons command.

* `example_simple/` is a simple Arduino program which requires the
  Arduino core and SoftwareSerial libraries.  It builds _in situ_
  rather than to a variant directory.

* `example_variant/` builds to a variant directory, `build/<board-name>/`.
  In addition to using Arduino libraries, it also provides a library
  of its own in `src/libraries/`.  Note that library sources do not
  need to be in a subdirectory.  And if placed in a subdirectory, then
  the name is arbitrary.  Libraries do not need to be in a
  subdirectory named `libraries`.