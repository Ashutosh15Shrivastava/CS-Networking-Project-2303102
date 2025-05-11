import socket
import threading
import pickle
import time
from packet import Packet, DISCOVER, OFFER, REQUEST, ACK, NOT_NEEDED, RELEASE, CLOSEACK,KEEPALIVE

class BroadcastServer:
    def __init__(self, host='localhost', port=5000):
        self.host = host
        self.port = port
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(10)
        
        # Store connected clients and servers with their socket connections
        self.dhcp_servers = {}  # {server_socket: server_info}
        self.clients = {}  # {client_socket: client_info}
        
        # Lock for thread safety
        self.lock = threading.Lock()
        self.tid1_to_client_socket = {}
        
        print(f"Broadcast server started on {self.host}:{self.port}")

    def start(self):
        #Start the broadcast server and listen for connections
        try:
            while True:
                client_socket, address = self.server_socket.accept()
                threading.Thread(target=self.handle_connection, args=(client_socket, address)).start()
        except KeyboardInterrupt:
            print("Shutting down broadcast server...")
        finally:
            self.server_socket.close()

    def handle_connection(self, connection, address):
        #Handle a new connection and determine if it's a DHCP server or client
        try:
            # Receive connection type (server or client)
            data = connection.recv(1024)
            connection_type = data.decode('utf-8')
            
            if connection_type == "SERVER":
                self.register_dhcp_server(connection, address)
            elif connection_type == "CLIENT":
                self.register_client(connection, address)
            else:
                print(f"Unknown connection type: {connection_type}")
                connection.close()
        except Exception as e:
            print(f"Error handling connection: {e}")
            connection.close()

    def register_dhcp_server(self, server_socket, address):
        #Register a new DHCP server
        with self.lock:
            server_id = len(self.dhcp_servers) + 1
            self.dhcp_servers[server_socket] = {
                'id': server_id,
                'address': address
            }
        
        print(f"DHCP Server {server_id} connected from {address}")
        
        # Start thread to listen for server messages
        threading.Thread(target=self.handle_server_messages, args=(server_socket, server_id)).start()

    def register_client(self, client_socket, address):
        # Register a new client
        with self.lock:
            client_id = len(self.clients) + 1
            self.clients[client_socket] = {
                'id': client_id,
                'address': address,
                'ip': '0.0.0.0'  # Initial IP
            }
        
        print(f"Client {client_id} connected from {address}")
        
        # Start thread to listen for client messages
        threading.Thread(target=self.handle_client_messages, args=(client_socket, client_id)).start()

    def handle_server_messages(self, server_socket, server_id):
        # Handle messages from DHCP servers
        try:
            while True:
                data = server_socket.recv(8192)
                if not data:
                    break
                
                # Deserialize the packet
                packet = Packet.deserialize(data)
                print(f"Received {packet.packet_type} packet from DHCP Server {server_id}")
                
                # Process the packet based on type
                if packet.packet_type == OFFER or packet.packet_type == ACK or packet.packet_type == CLOSEACK:
                    # Forward to the appropriate client using tid1
                    self.forward_to_client(packet)
                
        except Exception as e:
            print(f"Error handling server {server_id} messages: {e}")
        finally:
            self.disconnect_server(server_socket, server_id)

    def handle_client_messages(self, client_socket, client_id):
        # Handle messages from clients
        client_socket.settimeout(5.0) 
        try:
            while True:
                try:
                    data = client_socket.recv(8192)
                    if not data:
                        break
                except socket.timeout:
                    continue
                packet = Packet.deserialize(data)
                print(f"Received {packet.packet_type} packet from Client {client_id}")
                self.tid1_to_client_socket[packet.tid1] = client_socket
                if packet.packet_type == DISCOVER:
                    # Forward discovery packet to all DHCP servers
                    self.broadcast_to_dhcp_servers(packet)
                elif packet.packet_type in [REQUEST, NOT_NEEDED, RELEASE,KEEPALIVE]:
                    # Forward to the appropriate server using tid2
                    self.forward_to_server(packet)
                
        except Exception as e:
            print(f"Error handling client {client_id} messages: {e}")
        finally:
            self.disconnect_client(client_socket, client_id)

    def broadcast_to_dhcp_servers(self, packet):
        """Forward a discovery packet to all connected DHCP servers"""
        with self.lock:
            if not self.dhcp_servers:
                print("No DHCP servers available")
                return
            
            print(f"Broadcasting DISCOVER packet to {len(self.dhcp_servers)} DHCP servers")
            for server_socket in list(self.dhcp_servers.keys()):
                try:
                    server_socket.sendall(packet.serialize())
                except Exception as e:
                    print(f"Error sending to DHCP server: {e}")
                    self.disconnect_server(server_socket, self.dhcp_servers[server_socket]['id'])

    def forward_to_client(self, packet):
        #Forward a packet to the appropriate client using tid1
        with self.lock:
            target_client = None
            if packet.tid1 in self.tid1_to_client_socket:
                target_client = self.tid1_to_client_socket[packet.tid1]
            else:
                for client_socket,client_info in self.clients.items():
                # Find client by checking packets in transit or other criteria
                    try:
                    # Send test packet to check if this is the right client
                        test_packet = Packet(packet_type="TEST", tid1=packet.tid1)
                        client_socket.sendall(test_packet.serialize())
                    
                        client_socket.settimeout(2.0)
                        try:
                            response = client_socket.recv(8192)
                            response_packet = Packet.deserialize(response)
                    
                            if response_packet.tid1 == packet.tid1:
                                target_client = client_socket
                                self.tid1_to_client_socket[packet.tid1] = client_socket #newline
                                break
                        except socket.timeout:
                            print(f"Error forwarding to client: TIMEOUT")
                            continue

                        finally:
                            client_socket.settimeout(None)

                    except Exception as e:
                        print(f"Error forwarding to client: {e}")
                        continue
            
            if target_client:
                try:
                    print(f"Forwarding {packet.packet_type} packet to client {packet.tid2}")
                    target_client.sendall(packet.serialize())
                except Exception as e:
                    print(f"Error forwarding to client: {e}")
                    client_id = self.clients[target_client]['id']
                    self.disconnect_client(target_client, client_id)
            else:
                print(f"No client found for packet with tid1={packet.tid1}")

    def forward_to_server(self, packet):
        """Forward a packet to the appropriate server using tid2"""
        with self.lock:
            target_server = None
            for server_socket, server_info in self.dhcp_servers.items():
                try:
                    server_socket.sendall(packet.serialize())
                except Exception as e:
                    print(f"Error forwarding to server: {e}")
                    self.disconnect_server(server_socket, server_info['id'])

    def disconnect_server(self, server_socket, server_id):
        """Handle server disconnection"""
        with self.lock:
            if server_socket in self.dhcp_servers:
                del self.dhcp_servers[server_socket]
                print(f"DHCP Server {server_id} disconnected")
            
            try:
                server_socket.close()
            except:
                pass

    def disconnect_client(self, client_socket, client_id):
        """Handle client disconnection"""
        with self.lock:
            if client_socket in self.clients:
                del self.clients[client_socket]
                print(f"Client {client_id} disconnected")
            
            try:
                client_socket.close()
            except:
                pass

if __name__ == "__main__":
    server = BroadcastServer()
    server.start()
