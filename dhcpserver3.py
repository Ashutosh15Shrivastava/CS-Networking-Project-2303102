import socket
import threading
import time
import random
import pickle
from packet import Packet, DISCOVER, OFFER, REQUEST, ACK, NOT_NEEDED, RELEASE, CLOSEACK,KEEPALIVE

SERVER_ID = 3

class DHCPServer:
    def __init__(self, server_id=SERVER_ID, broadcast_host='localhost', broadcast_port=5000):
        self.server_id = server_id
        self.broadcast_host = broadcast_host
        self.broadcast_port = broadcast_port
        
        # Generate IP address pool for server 1 (192.168.1.x)
        base_ip = "192.168."+ str(server_id)+"."
        self.available_ips = [f"{base_ip}{i}" for i in range(2, 255)]
        self.non_available_ips = []
        self.non_available_timeout = {}
        
        # Track transaction IDs and their associated IP offers
        self.transactions = {}  # {tid2: (tid1, offered_ip)}
        
        # Socket connection to broadcast server
        self.socket = None
        self.connected = False
        
        self.timeout = 50
        # Lock for thread safety
        self.lock = threading.Lock()
        
        # Flag to control the server
        self.running = True
    
    def connect_to_broadcast(self):
        """Connect to the broadcast server"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.broadcast_host, self.broadcast_port))
            
            # Identify as a DHCP server
            self.socket.send("SERVER".encode('utf-8'))
            self.connected = True
            
            print(f"DHCP Server {self.server_id} connected to broadcast server")
            return True
        except Exception as e:
            print(f"Failed to connect to broadcast server: {e}")
            return False
    
    def start(self):
        """Start the DHCP server"""
        if not self.connect_to_broadcast():
            return
        
        # Start thread to receive messages from broadcast server
        receive_thread = threading.Thread(target=self.receive_messages)
        receive_thread.daemon = True
        receive_thread.start()
        
        # Start thread for server menu
        menu_thread = threading.Thread(target=self.show_menu)
        menu_thread.daemon = True
        menu_thread.start()
        cleanup_thread = threading.Thread(target=self.cleanup_stale_offers)
        cleanup_thread.daemon = True
        cleanup_thread.start()
        
        
        # Keep main thread alive
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.running = False
        finally:
            self.disconnect()
    
    def receive_messages(self):
        """Receive and process messages from the broadcast server"""
        try:
            while self.connected and self.running:
                data = self.socket.recv(8192)
                if not data:
                    break
                
                packet = Packet.deserialize(data)
                print(f"\nReceived {packet.packet_type} packet: {packet}")
                
                # Process packet based on type
                if packet.packet_type == DISCOVER:
                    self.handle_discover(packet)
                elif packet.packet_type == REQUEST and packet.tid2 in self.transactions:
                    self.handle_request(packet)
                elif packet.packet_type == NOT_NEEDED and packet.tid2 in self.transactions:
                    self.handle_not_needed(packet)
                elif packet.packet_type == RELEASE and packet.tid2 in self.transactions:
                    self.handle_release(packet)
                elif packet.packet_type == KEEPALIVE and packet.tid2 in self.transactions:
                    self.handle_keepalive(packet)
                
                # print("Menu: 1-Available IPs, 2-Non-Available IPs, 3-Disconnect")
        except Exception as e:
            print(f"Error receiving messages: {e}")
        finally:
            self.connected = False
    
    def handle_discover(self, packet):
        """Handle DISCOVER packet - send an OFFER if we have available IPs"""
        with self.lock:
            if not self.available_ips:
                print("No available IP addresses to offer")
                return
            
            # Generate a new tid2 for this transaction
            tid2 = ''.join(random.choices('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=8))
            
            # Select an IP to offer
            offered_ip = self.available_ips.pop(0)
            self.non_available_ips.append(offered_ip)
            self.non_available_timeout[offered_ip] = time.time() + 210
            
            # Store transaction info
            self.transactions[tid2] = (packet.tid1, offered_ip)
            
            # Create and send offer packet
            offer_packet = Packet(
                current_ip=packet.current_ip,
                tid1=packet.tid1,
                tid2=tid2,
                packet_type=OFFER,
                offering_ip=offered_ip
            )
            
            print(f"Sending OFFER for IP {offered_ip} with TID2={tid2}")
            self.socket.sendall(offer_packet.serialize())

    def handle_keepalive(self,packet):
        with self.lock:
            tid1, offered_ip = self.transactions[packet.tid2]
            if offered_ip in self.non_available_ips:
                self.non_available_timeout[offered_ip] = time.time() + 200
            
    def handle_request(self, packet):
        """Handle REQUEST packet - send an ACK"""
        with self.lock:
            tid1, offered_ip = self.transactions[packet.tid2]
            
            # Create and send ACK packet
            ack_packet = Packet(
                current_ip=packet.current_ip,
                tid1=tid1,
                tid2=packet.tid2,
                packet_type=ACK,
                offering_ip=offered_ip
            )

            self.non_available_timeout[offered_ip]=time.time()+200
            
            print(f"Sending ACK for IP {offered_ip}")
            self.socket.sendall(ack_packet.serialize())
            
            # Note: We keep the transaction record for potential release later
    
    def handle_not_needed(self, packet):
        """Handle NOT_NEEDED packet - return IP to pool"""
        with self.lock:
            tid1, offered_ip = self.transactions[packet.tid2]
            
            # Return IP to available pool
            if offered_ip in self.non_available_ips:
                self.non_available_ips.remove(offered_ip)
                self.available_ips.append(offered_ip)
                print(f"Returned IP {offered_ip} to available pool")
            
            # Clean up transaction
            del self.transactions[packet.tid2]
    
    def handle_release(self, packet):
        """Handle RELEASE packet - return IP to pool and send CLOSEACK"""
        with self.lock:
            tid1, offered_ip = self.transactions[packet.tid2]
            
            # Return IP to available pool
            if offered_ip in self.non_available_ips:
                self.non_available_ips.remove(offered_ip)
                self.available_ips.append(offered_ip)
                print(f"Released IP {offered_ip} back to available pool")
            
            # Create and send CLOSEACK packet
            closeack_packet = Packet(
                current_ip=packet.current_ip,
                tid1=tid1,
                tid2=packet.tid2,
                packet_type=CLOSEACK,
                offering_ip=None
            )
            
            print(f"Sending CLOSEACK for released IP {offered_ip}")
            self.socket.sendall(closeack_packet.serialize())
            
            # Clean up transaction
            del self.transactions[packet.tid2]
    
    def show_menu(self):
        """Display interactive menu for server"""
        while self.connected and self.running:
            print("\nMenu: 1-Available IPs, 2-Non-Available IPs, 3-Disconnect")
            try:
                choice = input("Select an option: ")
                
                if choice == '1':
                    with self.lock:
                        print("\nAvailable IP Addresses:")
                        for ip in self.available_ips:
                            print(f"  {ip}")
                
                elif choice == '2':
                    with self.lock:
                        print("\nNon-Available IP Addresses:")
                        for ip in self.non_available_ips:
                            print(f"  {ip}")
                
                elif choice == '3':
                    print("Disconnecting from broadcast server...")
                    self.disconnect()
                    break
                
                else:
                    print("Invalid option")
            
            except Exception as e:
                print(f"Error in menu: {e}")
    
    def display_available_addresses(self):
        """Periodically display available IP addresses"""
        while self.connected and self.running:
            time.sleep(30)  # Display every 30 seconds
            with self.lock:
                print("\nPeriodic update - Available IP Addresses:")
                for ip in self.available_ips:
                    print(f"  {ip}")
    
    def disconnect(self):
        """Disconnect from broadcast server"""
        self.running = False
        self.connected = False
        
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
        
        print(f"DHCP Server {self.server_id} disconnected")

    def cleanup_stale_offers(self):
        while self.running:
            time.sleep(1)
            to_remove = []
            for ip, timeout in list(self.non_available_timeout.items()):
                if timeout < time.time():
                    self.non_available_ips.remove(ip)
                    self.available_ips.append(ip)
                    to_remove.append(ip)
            for ip in to_remove:
                del self.non_available_timeout[ip] 

if __name__ == "__main__":
    print(f"Starting DHCP Server {SERVER_ID} (192.168.{SERVER_ID}.x)")
    server = DHCPServer(server_id=SERVER_ID)
    server.start()
