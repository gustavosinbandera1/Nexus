"""
Nexus - Nextion Upload Script by Max Zuidberg

This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""

import argparse
import struct
import serial
from serial.tools.list_ports import comports as availablePorts
from pathlib import Path
from math import ceil


class Nexus:
    NXEOL = b"\xff\xff\xff"
    NXACK = b"\x05"
    NXALL = b"\x08\x00\x00\x00\x00"

    def __init__(self, port="", uploadSpeed=0, connectSpeed=0, connect=True):
        self.uploadSpeed  = uploadSpeed
        self.connectSpeed = connectSpeed
        self.connected    = False
        self.touch        = None
        self.address      = 0
        self.model        = ""
        self.fwVersion    = -1
        self.mcuCode      = -1
        self.serialNum    = ""
        self.flashSize    = -1
        self.ports        = [p.name for p in availablePorts()]
        if port:
            if port not in self.ports:
                raise Exception("Specified port not available ({} not in {})".format(port, self.ports))
            else:
                self.ports.remove(port)
                self.ports.insert(0, port)

        self.ser  = serial.Serial()
        if connect:
            if not self.connect():
                raise Exception("Cannot connect to device.")

    def connect(self):
        defaultSpeeds = [2400, 4800, 9600, 19200, 31250, 38400, 57600, 74880, 115200, 230400, 250000, 256000, 460800, 500000, 512000, 921600]
        if self.connectSpeed:
            if self.connectSpeed in defaultSpeeds:
                defaultSpeeds.remove(self.connectSpeed)
            defaultSpeeds.insert(0, self.connectSpeed)

        for port in self.ports:
            print("Scanning port " + port)
            for speed in defaultSpeeds:
                print("  at {}baud/s... ".format(speed), end="")
                self.ser.close()
                self.ser.port = port
                self.ser.baudrate = speed
                self.ser.timeout  = 1000/speed + 0.030
                try:
                    self.ser.open()
                except:
                    break
                self.ser.reset_input_buffer()
                self.ser.write(b"DRAKJHSUYDGBNCJHGJKSHBDN\xff\xff\xffconnect\xff\xff\xff\xff\xffconnect\xff\xff\xff")
                data = b""
                available = -1
                while available != len(data):
                    available = self.ser.in_waiting
                    newData = self.ser.read_until(expected=self.NXEOL)
                    if newData:
                        data = newData
                    else:
                        break
                if not data.startswith(b"comok"):
                    print("Failed.")
                    continue
                self.ser.write(self.NXEOL)
                self.ser.read(42)
                self.connected=True
                data = data.lstrip(b"comok ").rstrip(self.NXEOL).split(b",")
                data[1] = data[1].split(b"-")[1] # discard reserved part of argument 1
                self.touch     = bool(int(data[0]))
                self.address   = int(data[1])
                self.model     = data[2].decode("ascii")
                self.fwVersion = int(data[3])
                self.mcuCode   = int(data[4])
                self.serialNum = data[5].decode("ascii")
                self.flashSize = int(data[6])
                self.port         = port
                self.connectSpeed = speed
                if not self.model:
                    raise Exception("Invalid model! Data: {}".format(data))
                if not self.uploadSpeed:
                    self.uploadSpeed = self.connectSpeed
                print("Success.")
                return True

        return False

    def sendCmd(self, cmd: str, *args):
        if not self.connected:
            raise Exception("Cannot send commands if not connected.")

        if args:
            cmd = str(cmd) + " " + "{}," * len(args)
            cmd = cmd[:-1]
        cmd = cmd.format(*args).encode("ascii")
        cmd += self.NXEOL
        if self.address:
            cmd = struct.pack("<H", self.address) + cmd
        self.ser.write(cmd)

    def ack(self):
        a = self.ser.read_until(self.NXACK)
        if not a.endswith(self.NXACK):
            raise Exception("Expected acknowledge ({}), got {}.".format(self.NXACK, a))

    def getFileSize(self, tftFilePath):
        with open(tftFilePath, "rb") as f:
            f.seek(0x3c)
            rawSize = f.read(struct.calcsize("<I"))
        fileSize = struct.unpack("<I", rawSize)[0]
        return fileSize

    def upload(self, tftFilePath):
        if not self.connected:
            raise Exception("Successful connection required for upload.")

        fileSize = self.getFileSize(tftFilePath)

        self.sendCmd("bs=42") # For some reason the first command after self.connect() always fails. Can be anything.
        self.sendCmd("dims=100")
        self.sendCmd("sleep=0")
        self.ser.reset_input_buffer()

        print("Initiating upload... ", end="")
        self.sendCmd("whmi-wris", fileSize, self.uploadSpeed, 1)
        self.ser.close()
        self.ser.baudrate = self.uploadSpeed
        self.ser.timeout  = 0.5
        try:
            self.ser.open()
        except:
            raise Exception("Cannot reopen port at upload baudrate.")
        self.ack()
        print("Success.")

        blockSize = 4096
        remainingBlocks = ceil(fileSize / blockSize)
        firstBlock = True
        progress, lastProgress = 0, 0
        with open(tftFilePath, "rb") as f:
            while remainingBlocks:
                self.ser.write(f.read(blockSize))
                remainingBlocks -= 1

                if firstBlock:
                    firstBlock = False
                    self.ser.timeout = 2 # Apparently the processing of the first block takes closer to 1s of time.
                    proceed = self.ser.read(len(self.NXALL))
                    if len(proceed) != len(self.NXALL) or not proceed.startswith(b"\x08"):
                        raise Exception("First block acknowledge (0x08) not received. Got {}.".format(proceed))
                    elif proceed != self.NXALL:
                        nextPos = struct.unpack_from("<I", proceed, 1)[0]
                        f.seek(nextPos)
                        remainingBlocks = ceil((fileSize - nextPos) / blockSize)
                        print("Skipped ressources.")
                    self.ser.timeout = 0.5 # return to normal timeout.

                else:
                    self.ack()
                progress = 100 * f.tell() // fileSize
                if progress != lastProgress:
                    print(progress, "% ", sep="", end="\r")
                    lastProgress = progress


if __name__ == "__main__":
    desc = """Nexus - Nextion Upload Script
              Upload TFT files to your Nextion screen using the advantages of the newer and faster
              upload protocol v1.2. Details at https://bit.do/unuf-nexus  
              Developped by Max Zuidberg, licensed under MPL-2.0"""
    parser = argparse.ArgumentParser(description=desc)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-l", "--list", action="store_true",
                        help="List all available serial ports.")
    group.add_argument("-i", "--input", metavar="TFT_FILE", type=str,
                        help="Path to the TFT file")
    parser.add_argument("-p", "--port", metavar="PORT", type=str, default="",
                        help="Optional serial port to use. By default Nexus scans all ports and uses "
                             "the first one where it finds a Nextion decive. Use -l to list all available "
                             "ports. ")
    parser.add_argument("-c", "--connect", metavar="BAUDRATE", type=int, required=False, default=0,
                        help="Preferred baudrate for the initial connection to the screen. If a connection at this "
                             "baudrate fails or if this argument is not given the script will try a list "
                             "of default baudrates")
    parser.add_argument("-u", "--upload", metavar="BAUDRATE", type=int, required=False, default=0,
                        help="Optional baudrate for the actual upload. If not specified, the baudrate at which the "
                             "connection has been established will be used for the upload, too (can be slow!).")

    args = parser.parse_args()
    ports = [p.name for p in availablePorts()]
    portsStr = ", ".join(ports)
    if args.list:
        print("List of available serial ports:")
        print(portsStr)
        exit()

    ports.append("")
    if args.port not in ports:
        parser.error("Port {} not found among the available ports: {}.".format(args.port, portsStr))

    tftPath = Path(args.input)
    if not tftPath.exists():
        parser.error("Invalid source file!")

    nxu = Nexus(port=args.port, connectSpeed=args.connect, uploadSpeed=args.upload)
    nxu.upload(tftPath)
