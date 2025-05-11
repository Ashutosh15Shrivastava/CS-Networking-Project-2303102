import pickle
import random
import string

# Packet Types
DISCOVER = "DISCOVER"
OFFER = "OFFER"
REQUEST = "REQUEST"
ACK = "ACK"
NOT_NEEDED = "NOT_NEEDED"
RELEASE = "RELEASE"
CLOSEACK = "CLOSEACK"
TEST = "TEST"
KEEPALIVE ="KEEPALIVE"

class Packet:
    def __init__(self, current_ip="0.0.0.0", tid1=None, tid2=None, packet_type=None, offering_ip=None):
        self.current_ip = current_ip
        self.tid1 = tid1 if tid1 else self._generate_transaction_id()
        self.tid2 = tid2
        self.packet_type = packet_type
        self.offering_ip = offering_ip
    
    def _generate_transaction_id(self):
        """Generate a random 8-character alphanumeric transaction ID"""
        return ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    
    def serialize(self):
        """Convert packet to bytes for network transmission"""
        return pickle.dumps(self)
    
    @staticmethod
    def deserialize(data):
        """Convert bytes back to packet object"""
        return pickle.loads(data)
    
    def __str__(self):
        """String representation of packet for logging"""
        return (f"Packet[Type={self.packet_type}, Current IP={self.current_ip}, "
                f"TID1={self.tid1}, TID2={self.tid2}, Offering IP={self.offering_ip}]")
