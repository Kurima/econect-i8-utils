# econect-i8-utils
[econect](https://econect.cnrs.fr/ "econect project homepage") is a European project studying biodiversity in the Occitanie region in France. Sensors will be deployed, some of them will need a way to send pictures with a relatively correct speed and a small energy cost. To achieve this, we use [Digi XBee 3 PRO](https://www.digi.com/products/models/xb3-24z8st "Digi XBee device page") devices connected with a UART/USB adapter to a [Jetson Nano](https://developer.nvidia.com/EMBEDDED/jetson-nano-developer-kit "Jetson Nano official webpage") / [Raspberry Pi](https://www.raspberrypi.org/ "Raspberry Pi official website") computer. This computer acts like a gateway between the sensors and our cloud platform, transferring data received from the IEEE 802.15.4 data link to the Internet, using a mobile connection.


This project provides a simplified Network/Transport Layer (I8TL) to answer our needs. This layer allows to transfert  data reliably from end devices to a coordinator, to fragment and reassemble big chunk of data, while hiding taking complexity away from its users. Implementations of [NeoCayenneLPP](https://neocampus.univ-tlse3.fr/_media/lora/neocayennelpp_lorawan-data-exchange.pdf "NeoCayenneLPP datasheet") and a simple file transfert wrapper (F8Wrapper) allowing to keep the file name end to end  are also included.  Scheduling is scheduled (🙃) to be part of this layer. 

Examples device (`i8_device.py`), receiver (`i8_receiver.py`) and  forwarder (`i8_forwarder.py`) are included alongside the library code.

# Initial XBee devices setup

You'll need [XCTU](https://www.digi.com/products/embedded-systems/digi-xbee/digi-xbee-tools/xctu "download link for XCTU") to configure your modules. Some preregistered profiles are given in the `xctu-profiles` folder. They can be directly used but are provided with a weak AES key (16 null bytes), a script is provided to generate a key and include it in the profiles (`./generate_profiles.sh`). To use this script [XMLStarlet](http://xmlstar.sourceforge.net/ "XMLStarlet official website") should be installed with your packet manager.  Another script is provided to help flashing profiles to the modules (`./flash_modules.sh`), its usage should be checked using the `--help` option.

If you have two modules to prepare,  `/dev/ttyUSB0`  being the coordinator and `/dev/ttyUSB1`  the end device, you should do something like:
```console
./generate_profiles.sh *.xpro
# updating: profile.xml (deflated 60%)
# updating: profile.xml (deflated 59%)

hexdump -ve '1/1 "%.2x"' aes.key
# 00000000000000000000000000000000% #It should be different in your case 😉

./flash_modules.sh --help
# Usage: ./flash_modules.sh -p <profile> [-f <module serial port> (default /dev/ttyUSB0)] [-s <speed|"slow"|"fast" (default: "fast")]

./flash_modules.sh -p econect_IEEE_802.15.4_coordinator_profile.xpro -f /dev/ttyUSB0 -s slow
# - Discovering radio module in serial port /dev/ttyUSB1 230400/8/N/1/N... [OK]
#         Radio module found:
# --------- Local XBeeDevice ---------
# Interface:        /dev/ttyUSB0 - 9600/8/N/1/N
# Working mode:     API 1
# Protocol:         802.15.4
# MAC Address:      0013A200FFFFFFFF
# 16-bit address:   FFFE
# Node Identifier:
# Device type:      Coordinator
# Hardware version: 42
# Firmware version: 200C
# 
# - Writing AT parameter: RE... [OK]
# - Writing AT parameter: MM... [OK]
# - Writing AT parameter: MY... [OK]
# - Writing AT parameter: EE... [OK]
# - Writing AT parameter: KY... [OK]
# - Writing AT parameter: AP... [OK]
# - Writing AT parameter: BD... [OK]
# - Writing parameters in flash... [OK]
# - Applying changes in the module... [OK]
# 
# 
# Profile applied successfully!

./flash_modules.sh -p econect_IEEE_802.15.4_end_device_profile.xpro -f /dev/ttyUSB1 -s slow > /dev/null
```

# Required components
If you install the library through pip, requirements shoud be installed, otherwise you'll have install them manually with `pip`:
```shell
pip3 install -r requirements.txt
```


# Start sending data using provided examples
**Before executing the scripts be sure to be part of the `dialout` or `uucp` group (depending on your linux distro)**

Create a `config.py` file (or a config submodule correctly configured) to define `SERVER_URL`, `EXAMPLES_FOLDER`, `EXAMPLES_FILE` and `RECEIVED_FOLDER` variables.

For example:
#### **`config.py`**
```python
from typing import Final, List

SERVER_URL      : Final[str]       = "https://localhost/posturl"
EXAMPLES_FOLDER : Final[str]       = "./example_files/"
EXAMPLES_FILES  : Final[List[str]] = ["pikachu.jpg"]
RECEIVED_FOLDER : Final[str]       = "./received_files/"


```

Connect the coordinator and start the `i8_receiver.py` script by providing its serial USB device name.
```shell
cd src
./i8_receiver.py /dev/ttyUSB0
```

On another computer (or the same) connect an end device and execute `./i8_device.py` by providing the end device serial USB device name
```shell
cd src
./i8_device.py /dev/ttyUSB1
```

And voilà! The files provided in the `EXAMPLE_FOLDER` folder and declared in the `EXAMPLE_FILES` variable will be sent to the receiver and can be found in the `RECEIVER_FOLDER`
