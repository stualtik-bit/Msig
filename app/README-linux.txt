MSIG 1.0.9 for Linux - algorithm editor for the DSP7000

Compatibility: tested only on the author's own DSP7000, from a Mac. This Linux
version has NOT been tested with the hardware yet; it uses the same code and
serial protocol as the Mac version. Feedback is welcome.

IMPORTANT NOTICE
MSIG is an independent project by Moteka (motekamusic.com).
- It is not associated with, endorsed by or supported by Eventide Inc., which is
  not responsible for any issue that may occur when MSIG is used with its products.
- MSIG contains no software, data or other material from the hardware
  manufacturer. The module list it needs is read from your own unit.
- All product names belong to their respective owners.
MSIG is provided "as is", without warranty of any kind. Back up your unit's
programs before sending anything to it. You use MSIG at your own risk.

REQUIREMENTS
- Linux on a 64-bit Intel/AMD PC (x86_64), glibc 2.17 or later (any common
  distribution from the last ten years). Not built for ARM (Raspberry Pi).
- A web browser (Firefox, Chromium...): the editor opens in a browser tab.
- USB-serial adapter (FTDI, Prolific PL2303, CH340, CP210x: drivers are
  included in Linux) and a straight-through DB9 cable (not null-modem).
  A built-in serial port (/dev/ttyS*) also works.
- On the DSP: serial link at 115200 baud with 2 stop bits, SysEx on, MIDI
  device ID 1.
- Nothing else to install: MSIG includes everything it needs.

INSTALLATION
1. Extract the archive:   tar xzf MSIG-1.0.9-linux-x86_64.tar.gz
2. Run:                    cd MSIG-1.0.9-linux-x86_64 && ./install.sh
   MSIG is installed for your user only (~/.local), with an entry in the
   applications menu and the 'msig' command.
3. Serial port access: your user must be in the 'dialout' group ('uucp' on
   Arch). install.sh tells you if it is needed:
       sudo usermod -aG dialout $USER
   then log out and back in.
To remove MSIG: ./install.sh --uninstall
You can also run MSIG without installing it: ./msig/msig

FIRST USE
1. Launch MSIG: the editor opens in your web browser (http://127.0.0.1:8000).
2. Choose the serial port (/dev/ttyUSB0 for most adapters), then click
   "Connect". MSIG connects by itself only to USB-serial adapters
   (/dev/ttyUSB*); /dev/ttyACM* ports (USB-MIDI devices, sound cards) and
   /dev/ttyS* are listed but must be chosen by hand.
3. First time only: click "Load module database". This takes
   about 30 seconds on a DSP7000 and can take several minutes on units with a
   larger database; the progress is shown at the bottom of the page.
   The module list is read from your DSP and kept on your computer.
4. "Quit" (top right) stops MSIG and releases the serial port. If you just
   close the tab, MSIG stops by itself after 5 minutes.

KEYBOARD SHORTCUTS
- Ctrl Z / Ctrl Shift Z: undo / redo. Ctrl X, Ctrl C, Ctrl V: cut, copy,
  paste the selected module. Ctrl D: duplicate. Delete: remove it.
- Ctrl S: save. Ctrl Shift S: save as. Ctrl O: open.

EDITING A PATCH
- Patch name: click it next to the MSIG title.
- Click a module to show its parameters in the inspector.
- Cables: drag from a coloured dot to another to connect two modules (only
  compatible signal types light up). Double-click an input dot to unplug it;
  double-click an output dot to remove all its cables. Ctrl Z undoes any change.
- "Random" creates a random but playable patch, 100% wet, in one of eight
  characters; Shift-click "Random" to enter a seed and get a patch again.
- "Send to DSP" replaces the algorithm loaded on the unit: save it first.

FILES AND LOGS
- Patches: .sig text files. Open and Save use your desktop's file dialogs
  when zenity (GNOME, Xfce...) or kdialog (KDE) is installed; otherwise the
  browser's own file picker and Downloads folder are used.
- Module list read from your unit: ~/.local/share/msig/
- Log: ~/.local/state/msig/msig.log

TROUBLESHOOTING
- "permission denied" on the port: add your user to the dialout group (see
  INSTALLATION), then log out and back in.
- "port busy": another program (or another MSIG) uses the port. ModemManager
  may probe /dev/ttyACM* ports; adapters on /dev/ttyUSB* are not affected.
- No serial port in the list: unplug and plug the adapter in again; check
  with  dmesg | tail  that Linux sees it.
- No answer from the DSP: check the cable (straight-through, not null-modem),
  115200 baud, SysEx on and MIDI device ID 1 on the unit.
- "Reply arrived garbled" on Get algorithm or Screen: the serial settings of
  the unit and of MSIG do not match. Check first that the unit's stop bits
  match MSIG's (2 by default; an H8000 set to 1 stop bit gives exactly this),
  then that the speeds are the same. Both are chosen next to the serial port
  menu, applied when you click Connect/Reconnect, and remembered.
- The browser does not open: open http://127.0.0.1:8000 yourself (the
  address is shown when MSIG is started from a terminal).

Version 1.0.9 - (c) Moteka - motekamusic.com / Free software. Not for resale.
