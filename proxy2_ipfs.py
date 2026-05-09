
# (c) by Valery Shmelev (Deutsche: Valery Shmeleff)
# Proxy2 - IPFS Server (with full processing of responses)
# IPFS-to-Network


import socket
import threading
import binascii
import subprocess
import time
import re

# ==================== CONFIGURATION ====================
LISTEN_PORT = 8222
EXTERNAL_IP = "192.168.0.95"  # Public IP your Hosting

HTTP_PREFIX = b"GET /wiki/ HTTP/1.1\r\nHost: en.euwiki.io\r\nUser-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36\r\nAccept: text/html\r\nAccept-Language: en-EN,en;q=0.9\r\nAccept-Encoding: gzip, deflate, br\r\nConnection: keep-alive\r\n\r\n"
SEPARATOR = b"\n===END===\n"

# ==================== FUNCTIONS ====================

def parse_request(data: bytes) -> tuple:
    """Parses an HTTP request and returns (host, port, is_connect)"""
    try:
        text = data.decode('ascii', errors='ignore')
        
        # CONNECT request
        match = re.search(r'CONNECT\s+([^\s:]+)(?::(\d+))?', text, re.IGNORECASE)
        if match:
            host = match.group(1)
            port = int(match.group(2)) if match.group(2) else 443
            return (host, port, True)
        
        # A regular HTTP request
        match = re.search(r'Host:\s*([^\r\n]+)', text, re.IGNORECASE)
        if match:
            host = match.group(1).strip()
            return (host, 80, False)
        
        return (None, None, False)
    except:
        return (None, None, False)

def extract_hex_data(data: bytes) -> bytes:
    """Extracts and decodes HEX data from a packet with a prefix"""
    if data.startswith(HTTP_PREFIX):
        data = data[len(HTTP_PREFIX) + len(SEPARATOR):]
    
    # Decode all HEX strings
    result = b""
    lines = data.split(b'\n')
    for line in lines:
        line = line.strip()
        if line:
            try:
                result += binascii.unhexlify(line)
            except:
                pass
    return result

def encode_data(data: bytes) -> bytes:
    """Encodes data in HEX with a prefix"""
    hex_data = binascii.hexlify(data) + b"\n"
    return HTTP_PREFIX + SEPARATOR + hex_data

def forward_data(src, dst, prefix_expected=True):
    """Forwards data from src to dst with decoding/encoding"""
    try:
        while True:
            chunk = src.recv(8192)
            if not chunk:
                break
            
            if prefix_expected:
                # Client data (with prefix) → Internet (without prefix)
                decoded = extract_hex_data(chunk)
                if decoded:
                    dst.send(decoded)
            else:
                # Internet data (without prefix) → client (with prefix)
                encoded = encode_data(chunk)
                dst.send(encoded)
    except:
        pass

def handle_tunnel(client_sock, addr):
    """Handles P2P connections from IPFS"""
    internet_sock = None
    try:
        # We receive the first request
        data = client_sock.recv(8192)
        if not data:
            return
        
        print(f"[*] {addr} Received {len(data)} bytes")
        
        # Extract and decode the request
        request = extract_hex_data(data)
        if not request:
            print(f"[!] {addr} Failed to decode request")
            return
        
        # Parsing the query
        host, port, is_connect = parse_request(request)
        if not host:
            print(f"[!] {addr} Failed to parse request")
            return
        
        print(f"[*] {addr} REQUEST → {host}:{port} (CONNECT={is_connect})")
        
        # Connecting to the target server
        internet_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        internet_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if EXTERNAL_IP:
            internet_sock.bind((EXTERNAL_IP, 0))
        internet_sock.settimeout(30)
        internet_sock.connect((host, port))
        internet_sock.settimeout(None)
        
        # If it's CONNECT, we send a response to the browser
        if is_connect:
            response = b"HTTP/1.1 200 Connection established\r\n\r\n"
            encoded_response = encode_data(response)
            client_sock.send(encoded_response)
            print(f"[*] {addr} Sent 200 CONNECT response")
            
# Now we're sending data in both directions
# Data from the client (TLS) → Internet
            t1 = threading.Thread(target=forward_data, args=(client_sock, internet_sock, True))
            # Data from the Internet → to the client (TLS)
            t2 = threading.Thread(target=forward_data, args=(internet_sock, client_sock, False))
            t1.daemon = True
            t2.daemon = True
            t1.start()
            t2.start()
            
            t1.join()
            t2.join()
        else:
# Regular HTTP request
# Sending a request to the internet
            internet_sock.send(request)
            
            # We receive a response and send it to the client.
            response = b""
            while True:
                chunk = internet_sock.recv(8192)
                if not chunk:
                    break
                response += chunk
            
            encoded_response = encode_data(response)
            client_sock.send(encoded_response)
        
    except Exception as e:
        print(f"[!] {addr} Error: {e}")
    finally:
        try:
            client_sock.close()
        except:
            pass
        try:
            if internet_sock:
                internet_sock.close()
        except:
            pass

def main():
    print("=" * 60)
    print("PROXY2 (Server) - IPFS P2P Mode (FIXED)")
    print("=" * 60)
    print(f"[*] External IP: {EXTERNAL_IP}")
    print(f"[*] Listening port: {LISTEN_PORT}")
    
    # Запускаем ipfs p2p listen
    cmd = ['ipfs', 'p2p', 'listen', '/x/http-proxy/1.0.0', f'/ip4/127.0.0.1/tcp/{LISTEN_PORT}']
    print(f"[*] Starting: {' '.join(cmd)}")
    listener_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    
    # Create a TCP server to accept connections from IPFS
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('127.0.0.1', LISTEN_PORT))
    server.listen(100)
    print(f"[*] Waiting for P2P connections...")
    
    try:
        while True:
            client, addr = server.accept()
            client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            print(f"[+] P2P connection from {addr}")
            t = threading.Thread(target=handle_tunnel, args=(client, addr))
            t.daemon = True
            t.start()
    except KeyboardInterrupt:
        print("\n[*] Shutting down...")
    finally:
        server.close()
        listener_process.terminate()

if __name__ == "__main__":
    main()
# https://oflameron.com

