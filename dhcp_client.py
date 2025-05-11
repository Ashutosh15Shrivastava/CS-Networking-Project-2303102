import socket
import threading
import time
import random
import pickle
import io
from packet import Packet, DISCOVER, OFFER, REQUEST, ACK, NOT_NEEDED, RELEASE, CLOSEACK,KEEPALIVE

class DHCPClient:
    def __init__(self, client_id, broadcast_host='localhost', broadcast_port=5000):
        self.client_id = client_id
        self.broadcast_host = broadcast_host
        self.broadcast_port = broadcast_port
        
        # Client state
        self.current_ip = "0.0.0.0"
        self.address_data = 0  # 0 = no address, 1 = has address
        self.tid1 = None
        self.tid2 = None
        self.lease_time = 200  # seconds
        self.lease_timer = None
        self.lease_start_time = None
        
        # Offers received during DHCP discovery
        self.pending_offers = []
        self.offer_timeout = 15  # seconds to wait for offers
        self.offer_timer = None
        
        # Socket connection to broadcast server
        self.socket = None
        self.connected = False
        
        # Lock for thread safety
        self.lock = threading.Lock()
        
        # Flag to control the client
        self.running = True
    
    def connect_to_broadcast(self):
        # Connect to the broadcast server
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.broadcast_host, self.broadcast_port))
            
            # Identify as a client
            self.socket.send("CLIENT".encode('utf-8'))
            self.connected = True
            
            print(f"Client {self.client_id} connected to broadcast server")
            return True
        except Exception as e:
            print(f"Failed to connect to broadcast server: {e}")
            return False
    
    def start(self):
        # Start the DHCP client
        if not self.connect_to_broadcast():
            return
        print("work2")
        # Start thread to receive messages from broadcast server
        receive_thread = threading.Thread(target=self.receive_messages)
        receive_thread.daemon = True
        receive_thread.start()
        
        # Start thread for client menu
        menu_thread = threading.Thread(target=self.show_menu)
        menu_thread.daemon = True
        menu_thread.start()
        
        # Keep main thread alive
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.running = False
        finally:
            self.disconnect()
    
    def receive_messages(self):
        # Receive and process messages from the broadcast server
        try:
            while self.connected and self.running:
                data = self.socket.recv(8192)
                if not data:
                    print("[ERROR] No data")
                    break

                buffer = io.BytesIO(data)
                try:
                    packet = pickle.load(buffer)
                except EOFError:
                    print("[ERROR] Failed to load packet: Incomplete data")
                except pickle.UnpicklingError:
                    print("[ERROR] Unpickling error: Data might be corrupted")
                if packet.packet_type == "TEST":
                    if self.tid1 is not None and packet.tid1 == self.tid1:
                        self.socket.sendall(packet.serialize())
                    continue

                
                print(f"\nReceived {packet.packet_type} packet: {packet}")
                
                # Process packet based on type
                if packet.packet_type == OFFER:
                    self.handle_offer(packet)
                elif packet.packet_type == ACK:
                    self.handle_ack(packet)
                elif packet.packet_type == CLOSEACK:
                    self.handle_closeack(packet)
                
                # print("Menu: 1-Request IP, 2-Release IP, 3-Refresh Lease, 0-Exit")
        except Exception as e:
            print(f"Error receiving messages: {e}")
        finally:
            self.connected = False
    
    def handle_offer(self, packet):
        # Handle OFFER packet - add to pending offers list
        with self.lock:
            if self.tid1 == packet.tid1 and self.address_data == 0:
                print(f"Received offer for IP {packet.offering_ip} from a DHCP server")
                self.pending_offers.append(packet)
    
    def handle_ack(self, packet):
        # Handle ACK packet - update client IP
        with self.lock:
            if self.tid1 == packet.tid1 and self.tid2 == packet.tid2:
                self.current_ip = packet.offering_ip
                self.address_data = 1
                print(f"IP address assigned: {self.current_ip}")
                
                # Start lease timer
                self.start_lease_timer()
    
    def handle_closeack(self, packet):
        # Handle CLOSEACK packet - reset client IP
        with self.lock:
            if self.tid1 == packet.tid1 and self.tid2 == packet.tid2:
                self.current_ip = "0.0.0.0"
                self.address_data = 0
                self.tid1 = None
                self.tid2 = None
                print("IP address released successfully")
                
                # Cancel lease timer if active
                self.cancel_lease_timer()
    
    def request_ip(self):
        # Request an IP address from DHCP servers
        with self.lock:
            if self.address_data == 1:
                print("You already have an IP address. Release it first.")
                return
            
            # Generate a new transaction ID
            self.tid1 = ''.join(random.choices('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=8))
            self.pending_offers = []
            
            # Create and send discover packet
            discover_packet = Packet(
                current_ip=self.current_ip,
                tid1=self.tid1,
                tid2=None,
                packet_type=DISCOVER,
                offering_ip=None
            )
            
            print(f"Sending DISCOVER packet with TID1={self.tid1}")
            self.socket.sendall(discover_packet.serialize())
            
            # Set timer to select from received offers
            self.offer_timeout = 5
            self.offer_timer = threading.Timer(self.offer_timeout, self.select_offer)
            self.offer_timer.daemon = True
            self.offer_timer.start()
    
    def select_offer(self):
        # Select an offer from the pending offers after timeout
        with self.lock:
            if not self.connected:
                print("Socket disconnected before sending offers.") # Additional
                return

            if not self.pending_offers:
                print("No DHCP offers received. Try again.")
                #self.tid1 = None
                return
            
            # Select a random offer
            selected_offer = random.choice(self.pending_offers)
            self.tid2 = selected_offer.tid2
            print(f"Selected offer for IP {selected_offer.offering_ip}")
            
            # Send request packet for the selected offer
            request_packet = Packet(
                current_ip=self.current_ip,
                tid1=self.tid1,
                tid2=self.tid2,
                packet_type=REQUEST,
                offering_ip=selected_offer.offering_ip
            )
            
            print(f"Sending REQUEST packet for IP {selected_offer.offering_ip}")
            self.socket.sendall(request_packet.serialize())
            print("Pending offers at selection time:")
            for offer in self.pending_offers:
                print(f"- {offer.offering_ip}, tid2={offer.tid2}")
            # Send not-needed packets for the other offers
            for offer in self.pending_offers:
                if offer.tid2 != selected_offer.tid2:
                    not_needed_packet = Packet(
                        current_ip=self.current_ip,
                        tid1=self.tid1,
                        tid2=offer.tid2,
                        packet_type=NOT_NEEDED,
                        offering_ip=offer.offering_ip
                    )
                    
                    print(f"Sending NOT_NEEDED packet for IP {offer.offering_ip}")
                    try:
                        self.socket.sendall(not_needed_packet.serialize())
                        time.sleep(0.1)  
                    except Exception as e:
                        print(f"Error sending NOT_NEEDED packet: {e}")
            # Clear pending offers
            self.pending_offers = []
    
    def release_ip(self):
        # Release the currently assigned IP address
        with self.lock:
            if self.address_data == 0:
                print("You don't have an IP address to release.")
                return
            
            # Create and send release packet
            release_packet = Packet(
                current_ip=self.current_ip,
                tid1=self.tid1,
                tid2=self.tid2,
                packet_type=RELEASE,
                offering_ip=None
            )
            
            print(f"Sending RELEASE packet for IP {self.current_ip}")
            self.socket.sendall(release_packet.serialize())
            
            # Cancel lease timer if active
            self.cancel_lease_timer()
    
    def start_lease_timer(self):
        # Start the lease timer
        self.cancel_lease_timer()  # Cancel any existing timer
        
        self.lease_start_time = time.time()
        self.lease_timer = threading.Timer(self.lease_time, self.lease_expired)
        self.lease_timer.daemon = True
        self.lease_timer.start()
        
        print(f"Lease timer started. IP {self.current_ip} will expire in {self.lease_time} seconds.")
    
    def refresh_lease(self):
        """Refresh the lease timer"""
        with self.lock:
            if self.address_data == 0:
                print("You don't have an IP address to refresh.")
                return
            keepalive_packet = Packet(
                current_ip=self.current_ip,
                tid1=self.tid1,
                tid2=self.tid2,
                packet_type=KEEPALIVE,
                offering_ip=None
            )
            elapsed = time.time() - self.lease_start_time
            remaining = max(0, self.lease_time - elapsed)
            print(f"Current lease time: {int(remaining)} seconds")     #bhjdkd
            print(f"Sending Keepalive packet for IP {self.current_ip}")
            self.socket.sendall(keepalive_packet.serialize())
                        
            self.start_lease_timer()
            print(f"Lease refreshed. IP {self.current_ip} will expire in {self.lease_time} seconds.")
    
    def lease_expired(self):
        # Handle lease expiration
        print(f"\nLease expired for IP {self.current_ip}")
        self.release_ip()
    
    def cancel_lease_timer(self):
        # Cancel the lease timer if active
        if self.lease_timer:
            self.lease_timer.cancel()
            self.lease_timer = None
    
    def show_menu(self):
        # Display interactive menu for client
        while self.connected and self.running:
            print("\nMenu: 1-Request IP, 2-Release IP, 3-Refresh Lease, 0-Exit")
            print(f"Current IP: {self.current_ip}")
            
            if self.lease_start_time and self.address_data == 1:
                elapsed = time.time() - self.lease_start_time
                remaining = max(0, self.lease_time - elapsed)
                print(f"Lease time remaining: {int(remaining)} seconds")
            
            try:
                choice = input("Select an option: ")
                
                if choice == '1':
                    self.request_ip()
                
                elif choice == '2':
                    self.release_ip()
                
                elif choice == '3':
                    self.refresh_lease()
                
                elif choice == '0':
                    print("Exiting...")
                    self.disconnect()
                    break
                
                else:
                    print("Invalid option")
            
            except Exception as e:
                print(f"Error in menu: {e}")
    
    def disconnect(self):
        # Disconnect from broadcast server
        self.running = False
        self.connected = False
        
        # Release IP if we have one
        if self.address_data == 1:
            self.release_ip()
            time.sleep(1)  # Give some time for the release packet to be sent
        
        if self.socket:
            try:
                time.sleep(1)
                self.socket.close()
            except:
                pass
        
        print(f"Client {self.client_id} disconnected")

if __name__ == "__main__":
    import sys
    
    client_id = 1
    if len(sys.argv) > 1:
        client_id = int(sys.argv[1])
    
    client = DHCPClient(client_id)
    client.start()