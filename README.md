# RF50-Klipper


The current repository contains all used files for configuring a BLOCKS RF50 printer.
Including klipper extras for some components of the printer.





## Adding configurations 

For the configurations to be updated 

        cd ~/printer_data
        
        mkdir ~/printer_data/config/config
        mkdir ~/printer_data/config/hardware

        ln -srf ~/RF50-Klipper/hardware/* config/config/
        ln -srf ~/RF50-Klipper/config/* config/config/

It is also necessary to copy the printer and variables configuration files to the `~/printer_data/config` directory 


        cp ~/RF50-Klipper/printer.cfg ~/printer_data/config/printer.cfg
        cp ~/RF50-Klipper/variables.cfg ~/printer_data/config/variables.cfg


Running the previous commands will create symlinks to all configuration files on the RF50-Klipper repo directory.
To be able to update the configuration files we can also add a moonraker`[update_manager RF50-Klipper]` entry so that the files with a corresponding symlink can be updated via moonraker


        [update_manager RF50-Klipper]
        type: git_repo
        path: ~/RF50-Klipper
        origin: https://github.com/BlocksTechnology/RF50-Klipper.git
        managed_services: klipper





# Flash Octopus Pro 

    TODO: Need to make this section readable

This file contains common pin mappings for the BigTreeTech Octopus and Octopus Pro boards. To use this config, start by identifying the micro-controller on the board - it may be an STM32F446, STM32F429, or an STM32H723.  Select the appropriate micro-controller in "make menuconfig" and select "Enable low-level configuration options". For STM32F446 boards the firmware should be compiled with a "32KiB bootloader" and a "12MHz crystal" clock reference. For STM32F429 boards use a "32KiB bootloader" and an "8MHz crystal". For STM32H723 boards use a "128KiB bootloader" and a "25Mhz crystal".




Important STM32H723
128KiB | 25 Mhz crystal 
USB TO CAN BRIDGE 

can on pd0 and pd1 


set board on dfu mode 


cd klipepr 

make flash FLASH_DEVICE=id that is on lsusb


or using dfu-util etc etc 

$ dfu-util -a 0 -d 0483:df11 --dfuse-address 0x08000000 -D ~/CanBoot/out/canboot.bin

$ dfu-util -a 0 -d 0483:df11 --dfuse-address 0x08002000 -D out/klipper.bin



bootloader entry 

cd klipper/scripts
> python3 -c 'import flash_usb as u; u.enter_bootloader("<DEVICE>")'
Entering bootloader on <DEVICE>


With canbus katapult flash tool  

python3 ./katapult/scripts/flashtool.py -i <CAN_IFACE> -u <UUID> -r



query flash 

~/klippy-env/bin/python ~/klipper/scripts/canbus_query.py can0
