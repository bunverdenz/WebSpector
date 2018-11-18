#!/usr/bin/env python3

import errno
import logging
import multiprocessing
import os
import signal
import socket
import struct
import subprocess

WEBSITE_TIMEOUT = 5

# Protocol Definition
#
# Request
#
# [Header]
# Magic(1byte): \xff
# Option(1byte)
#   \x01: open Chrome
#   \x02: open Firefox
#   \x03: open IE(Windows only)
#   \x04: open Safari(Mac only)
# Body Length(4byte, big-endian)
#
# [Body]
# Target website
#
#
# Response
#
# [Header]
# Magic(1byte): \xfe
#
# [Body]
# Code(1byte)
#   \x00: success
#   \x01: fail

class ProtocolError(Exception):
    pass

class CTimeoutError(Exception):
    pass

class Timeout:
    def __init__(self, sec=10, error_message=os.strerror(errno.ETIME)):
        self.sec = sec
        self.error_message = error_message

    def __enter__(self):
        signal.signal(signal.SIGALRM, self._handle_timeout)
        signal.alarm(self.sec)

    def __exit__(self, *args):
        signal.alarm(0)

    def _handle_timeout(self, signum, frame):
        raise CTimeoutError(self.error_message)

def handle(conn, address, timeout):
    global browsers
    global environ
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger("process-{}".format(address))
    logger.debug("Connected {} at {}".format(conn, address))
    try:
        with Timeout(sec=timeout):
            # parse header
            if conn.recv(1) != "\xff":
                raise ProtocolError("Illegal magic number")
            option = conn.recv(1)
            if option not in browsers:
                raise ProtocolError("Illegal option")
            body_length = struct.unpack(">I", conn.recv(4))[0]

            res = body_length
            body = b""
            while res > 0:
                data = conn.recv(1024 if res > 1024 else res)
                res -= len(data)
                body += data

            # do something...
            # TODO: implement web browser execution
            try:
                if option == "\x01":
                    subprocess.call([browsers[option],
                                     "--allow-running-insecure-content",
                                     "--ignore-certificate-errors",
                                     "--ignore-urlfetcher-cert-requests",
                                     "--disable-gpu", "--enable-logging=stderr",
                                     "--v=2", "--no-sandbox",
                                     body.decode("utf-8")], env=environ, timeout=WEBSITE_TIMEOUT)
                elif option == "\x02":
                    subprocess.call([browsers[option], body.decode("utf-8")], env=environ, timeout=WEBSITE_TIMEOUT)
                elif option == "\x03":
                    subprocess.call([browsers[option], body.decode("utf-8")], env=environ, timeout=WEBSITE_TIMEOUT)
                elif option == "\x04":
                    subprocess.call([browsers[option], body.decode("utf-8")], env=environ, timeout=WEBSITE_TIMEOUT)
                else:
                    raise ValueError("Illegal option value passed")
            except subprocess.TimeoutExpired:
                pass

            conn.sendall(b"\xfe\x00")
    except ProtocolError as e:
        logger.exception("Protocol error occured: {}".format(str(e)))
        conn.sendall(b"AAAA\xfe\x01")
    except CTimeoutError:
        logger.exception("Timeout error occured")
        conn.sendall(b"\xfe\x01")
    except IOError:
        logger.exception("IO error... maybe connection loss")
    finally:
        logger.debug("Closing {}".format(address))
        conn.close()

class WorkerServer:
    def __init__(self, host, port, timeout=30):
        self.logger = logging.getLogger("WorkerServer")
        self._host = host
        self._port = port
        self._timeout = timeout

    def start(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind((self._host, self._port))
        self.socket.listen(16)
        self.logger.debug("Start to listen")

        while True:
            conn, address = self.socket.accept()
            self.logger.debug("Accepted {}".format(address))
            process = multiprocessing.Process(target=handle, args=(conn, address, self._timeout))
            process.daemon = True
            process.start()
            self.logger.debug("Process {} started".format(process))

if __name__ == "__main__":
    global environ
    global browsers
    import platform
    system = platform.system()
    if system == "Windows":
        browsers = {
            "\x01": "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
            "\x02": "C:\\Program Files\\Mozilla Firefox\\firefox.exe",
            "\x03": "C:\\Program Files\\Internet Explorer\\iexplore.exe"
        }
        environ = os.environ
    elif system == "Linux":
        browsers = {
            "\x01": "/usr/bin/google-chrome",
            "\x02": "/usr/bin/firefox"
        }
        environ = os.environ
        environ["DISPLAY"] = ":1"
        subprocess.call("./linux-vscreen.sh")
    elif system == "Darwin":
        browsers = {
            "\x01": "/Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome",
            "\x02": "/Applications/Firefox.app/Contents/MacOS/firefox-bin",
            "\x04": "/Applications/Safari.app/Contents/MacOS/Safari"
        }
        environ = os.environ
    else:
        raise Exception("Unknown os: {}".format(system))
    del system
    del platform

    logging.basicConfig(level=logging.DEBUG)
    server = WorkerServer("0.0.0.0", 31333, timeout=10)
    try:
        logging.info("Server up")
        server.start()
    except:
        logging.exception("Unexpected exception")
    finally:
        logging.info("Shutting down...")
        for process in multiprocessing.active_children():
            logging.info("Shutting down process {}".format(process))
            process.terminate()
            process.join()
    logging.info("Server down")