
# (c) by Valery Shmelev (Deutsche: Valery Shmeleff)
# Proxy1 - IPFS Client (with full processing of responses)
# Browser-to-IPFS

import socket
import threading
import binascii
import subprocess
import time
import re

# ==================== CONFIGURATION ====================
LISTEN_IP = "10.10.0.1"
LISTEN_PORT = 8443
SERVER_PEER_ID = "12D3Ko74Hsk1DYv1SQY64nC8zub3x63D7tBjde7ZQaroUgdpQ6cz"
PROTOCOL = "/x/http-proxy/1.0.0"

HTTP_PREFIX = b"GET /wiki/ HTTP/1.1\r\nHost: en.euwiki.io\r\nUser-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36\r\nAccept: text/html\r\nAccept-Language: en-EN,en;q=0.9\r\nAccept-Encoding: gzip, deflate, br\r\nConnection: keep-alive\r\n\r\n"
SEPARATOR = b"\n===END===\n"

# ==================== FUNCTIONS ====================

def extract_host(data: bytes) -> str:
    """Extracts the host from an HTTP request"""
    try:
        text = data.decode('ascii', errors='ignore')
        match = re.search(r'CONNECT\s+([^\s:]+)', text, re.IGNORECASE)
        if match:
            return match.group(1)
        match = re.search(r'Host:\s*([^\r\n]+)', text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return "unknown"
    except:
        return "unknown"

def encode_data(data: bytes) -> bytes:
    """Encodes data in HEX with a prefix"""
    hex_data = binascii.hexlify(data) + b"\n"
    return HTTP_PREFIX + SEPARATOR + hex_data

def decode_data(data: bytes) -> bytes:
    """Decodes data from HEX (removing prefix)"""
    if data.startswith(HTTP_PREFIX):
        data = data[len(HTTP_PREFIX) + len(SEPARATOR):]
    
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

def forward_to_tunnel(tunnel_sock, client_sock):
    """Forwards data from the client into the tunnel (with encryption)"""
    try:
        while True:
            data = client_sock.recv(8192)
            if not data:
                break
            encoded = encode_data(data)
            tunnel_sock.send(encoded)
    except:
        pass

def forward_to_client(tunnel_sock, client_sock):
    """Forwards data from the tunnel to the client (with decoding)"""
    buffer = b""
    try:
        while True:
            chunk = tunnel_sock.recv(8192)
            if not chunk:
                break
            buffer += chunk
            
            # We check if there are complete packages
            while b'\n' in buffer:
                line, buffer = buffer.split(b'\n', 1)
                if line.strip():
                    decoded = decode_data(line + b'\n')
                    if decoded:
                        client_sock.send(decoded)
    except:
        pass

def handle_browser(client_sock, client_addr):
    """Handles one connection from the browser"""
    process = None
    tunnel = None
    
    try:
        # We receive the first request from the browser
        request = client_sock.recv(8192)
        if not request:
            return
        
        host = extract_host(request)
        print(f"[*] {client_addr} REQUEST → {host}")
        
        # Finding a free port for the tunnel
        temp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        temp_sock.bind(('127.0.0.1', 0))
        local_port = temp_sock.getsockname()[1]
        temp_sock.close()
        
        # Launching an IPFS tunnel
        cmd = ['ipfs', 'p2p', 'forward', PROTOCOL, f'/ip4/127.0.0.1/tcp/{local_port}', f'/p2p/{SERVER_PEER_ID}']
        print(f"[*] Starting: {' '.join(cmd)}")
        process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)  # We are waiting for the tunnel to be installed.
        
        # Connecting to the tunnel
        tunnel = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tunnel.connect(('127.0.0.1', local_port))
        tunnel.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        
        # Sending the first request
        encoded_request = encode_data(request)
        tunnel.send(encoded_request)
        
        # Creating streams for bidirectional forwarding
        t1 = threading.Thread(target=forward_to_tunnel, args=(tunnel, client_sock))
        t2 = threading.Thread(target=forward_to_client, args=(tunnel, client_sock))
        t1.daemon = True
        t2.daemon = True
        t1.start()
        t2.start()
        
        # We are waiting for the completion
        t1.join()
        t2.join()
        
    except Exception as e:
        print(f"[!] {client_addr} Error: {e}")
    finally:
        try:
            if tunnel:
                tunnel.close()
        except:
            pass
        try:
            if process:
                process.terminate()
        except:
            pass
        try:
            client_sock.close()
        except:
            pass

def main():
    print("=" * 60)
    print("PROXY1 (Client) - IPFS P2P Mode (FIXED)")
    print("=" * 60)
    print(f"[*] Target Peer ID: {SERVER_PEER_ID}")
    print(f"[*] Protocol: {PROTOCOL}")
    print(f"[*] Listening on: {LISTEN_IP}:{LISTEN_PORT}")
    
    # Create a server socket
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((LISTEN_IP, LISTEN_PORT))
    server.listen(100)
    print(f"[*] Server started. Press Ctrl+C to stop.")
    
    try:
        while True:
            client, addr = server.accept()
            client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            print(f"[+] Connection from {addr}")
            t = threading.Thread(target=handle_browser, args=(client, addr))
            t.daemon = True
            t.start()
    except KeyboardInterrupt:
        print("\n[*] Shutting down...")
    finally:
        server.close()

if __name__ == "__main__":
    main()
# https://oflameron.com


