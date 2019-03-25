import socket
import StringIO
import sys
import datetime
import time
import traceback
import bitstring
import struct
import binascii

from hpack import Encoder, Decoder
from http.frames.settings_frame import SettingsFrame
from http.frames.headers_frame import HeadersFrame
from http.frames.data_frame import DataFrame

class WSGIServer(object):
	address_family = socket.AF_INET
	socket_type = socket.SOCK_STREAM
	request_queue_size = 1

	def __init__(self, server_name, server_port):
		self.server_name = server_name
		self.server_port = server_port
		self.client_connection = None
		self.request_data = ""
		self.headers_set = []

	def set_app(self, application):
		self.application = application

	def handle_request(self):
		try:
			while True:
				self.request_data = self.client_connection.recv(4096)
				self.frame = self.parse_request(self.request_data)
				if self.frame.__class__ == SettingsFrame:
					sent_data = self.client_connection.sendall(self.frame.get_acknowledgement_frame().bytes)
				elif self.frame.__class__ == HeadersFrame:
					env = self.set_env()
					result = self.application(env, self.start_response)
					self.finish_response(result)
				else:
					pass
		except Exception:
			print("Error occurred in handle_request")
			print(traceback.format_exc())
	
	def parse_request(self, raw_data):
		if raw_data:
			raw_data = raw_data.replace("PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n", "")
			bits = bitstring.ConstBitStream(hex=binascii.hexlify(raw_data))
			frame_length = bits.read("uint:24")
			frame_type = bits.read("hex:8")
			if frame_type == '04':
				self.connection_settings = SettingsFrame(bits)
				return self.connection_settings
			if frame_type == '01':
				header_frame = HeadersFrame(self.connection_settings)
				header_frame.read(bits)
				return header_frame

	def set_env(self):
		env = {}

		env['wsgi.version'] = (1,0)
		env['wsgi.url_scheme'] = 'https'
		env['wsgi.input'] = StringIO.StringIO(self.request_data)
		env['wsgi.errors'] = sys.stderr
		env['wsgi.multithread'] = False
		env['wsgi.multiprocess'] = False
		env['wsgi.run_once'] = False
		env['REQUEST_METHOD'] = self.frame.get_method()
		env['PATH_INFO'] = self.frame.get_path()
		env['SERVER_NAME'] = self.server_name
		env['SERVER_PORT'] = str(self.server_port)

		return env

	def start_response(self, status, response_headers, exc_info=None):
		server_headers = {
			'Date': datetime.datetime.now().strftime('%a, %d %b %Y %H:%M:%S GMT'),
			'Server': 'WSGIServer 0.2'
		}

		server_headers.update({k: v for k, v in response_headers})
		self.headers_set = status, server_headers

	def finish_response(self, result):
		try:
			status, response_headers = self.headers_set
			response_headers[':status'] = status
			headers_frame = HeadersFrame(self.connection_settings)
			flags = {
				'end_stream': '0',
				'end_headers': '1',
				'padded': '0',
				'priority': '1'
			}
			header_bits = headers_frame.write(flags=flags, headers=response_headers)
			response = ""
			for data in result:
				response += data
			
			data_frame = DataFrame()
			data_bits = data_frame.write(flags={'end_stream': '1', 'padded': '0'}, response_body=response)
			response_bits = bitstring.pack("bits, bits", header_bits, data_bits)
			import ipdb; ipdb.set_trace()
			try:
				self.client_connection.sendall(response_bits.bytes)
			except OSError as e:
				print(e)
		except Exception as exp:
			print(traceback.format_exc())
			print(exp)
			print("Exception raised in finish response")