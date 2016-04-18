# encoding: utf-8
"""Run snmp_temper.py as a pass-persist module for NetSNMP.
See README.md for instructions.

Copyright 2012-2014 Philipp Adelt <info@philipp.adelt.net>

This code is licensed under the GNU public license (GPL). See LICENSE.md for details.
"""

import os
import sys
import syslog
import threading
import snmp_passpersist as snmp
from temperusb.temper import TemperHandler

ERROR_TEMPERATURE = 9999


def _unbuffered_handle(fd):  # pylint: disable=invalid-name
    return os.fdopen(fd.fileno(), 'w', 0)


class LogWriter(object):  # pylint: disable=too-few-public-methods
    """Utility class for writing to syslog"""
    def __init__(self, ident='temper-python', facility=syslog.LOG_DAEMON):
        syslog.openlog(ident, 0, facility)

    @staticmethod
    def write_log(message, prio=syslog.LOG_INFO):
        """Write message to syslog"""
        syslog.syslog(prio, message)

class Updater(object):  # pylint: disable=too-few-public-methods
    """Class to query the TEMPer USB device(s) and update SNMP OID's"""
    def __init__(self, snmp_pp, logger, testmode=False):
        self.logger = logger
        self.snmp_pp = snmp_pp
        self.testmode = testmode
        self.usb_lock = threading.Lock() # used to stop reinitialization interfering with update-thread
        self._initialize()

    def _initialize(self):
        with self.usb_lock:
            try:
                self.handler = TemperHandler()
                self.devs = self.handler.get_devices()
                self.logger.write_log('Found %i thermometer devices.' % len(self.devs))
                for i, d in enumerate(self.devs):
                    self.logger.write_log(
                        'Initial temperature of device #%i: %0.1f degree celsius' % (i, d.get_temperature())
                    )
            except Exception as e:  # pylint: disable=broad-except
                self.logger.write_log('Exception while initializing: %s' % str(e))

    def _reinitialize(self):
        # Tries to close all known devices and starts over.
        self.logger.write_log('Reinitializing devices')
        with self.usb_lock:
            for i, d in enumerate(self.devs):
                try:
                    d.close()
                except Exception as e:  # pylint: disable=broad-except
                    self.logger.write_log('Exception closing device #%i: %s' % (i, str(e)))
        self._initialize()

    def update(self):
        """Update the OID's with results"""
        if self.testmode:
            # APC Internal/Battery Temperature
            self.snmp_pp.add_int('318.1.1.1.2.2.2.0', 99)
            # Cisco devices temperature OIDs
            self.snmp_pp.add_int('9.9.13.1.3.1.3.1', 97)
            self.snmp_pp.add_int('9.9.13.1.3.1.3.2', 98)
            self.snmp_pp.add_int('9.9.13.1.3.1.3.3', 99)
        else:
            try:
                with self.usb_lock:
                    temperatures = [d.get_temperature() for d in self.devs]
                    self.snmp_pp.add_int('318.1.1.1.2.2.2.0', int(max(temperatures)))
                    for i, temperature in enumerate(temperatures[:3]): # use max. first 3 devices
                        self.snmp_pp.add_int('9.9.13.1.3.1.3.%i' % (i+1), int(temperature))
            except Exception as e:  # pylint: disable=broad-except
                self.logger.write_log('Exception while updating data: %s' % str(e))
                # Report an exceptionally large temperature to set off all alarms.
                # snmp_passpersist does not expose an API to remove an OID.
                for oid in ('318.1.1.1.2.2.2.0', '9.9.13.1.3.1.3.1', '9.9.13.1.3.1.3.2', '9.9.13.1.3.1.3.3'):
                    self.snmp_pp.add_int(oid, ERROR_TEMPERATURE)
                self.logger.write_log('Starting reinitialize after error on update')
                self._reinitialize()


def main():
    """Main method to start updating SNMP via the PassPersist protocol"""
    sys.stdout = _unbuffered_handle(sys.stdout)
    snmp_pp = snmp.PassPersist(".1.3.6.1.4.1")
    logger = LogWriter()
    upd = Updater(snmp_pp, logger, testmode=('--testmode' in sys.argv))
    snmp_pp.start(upd.update, 5) # update every 5s


if __name__ == '__main__':
    main()
