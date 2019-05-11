from http2.frames.headers_frame import HeadersFrame
from http2.frames.continuation_frame import ContinuationFrame
from http2.frames.data_frame import DataFrame
from http2.frames import utils

import asyncio
import queue

class Stream(object):
	def __init__(self, connection_settings, header_encoder, header_decoder, client_connection):
		self.connection_settings = connection_settings
		self.header_encoder = header_encoder
		self.header_decoder = header_decoder
		self.client_connection = client_connection
		self.response_queue = queue.Queue()

	async def send_response(self, event):
		if event["type"] == "http.response.start":
			headers_frame = HeadersFrame(self.header_encoder, self.header_decoder)
			response_headers = {}
			for h in event["headers"]:
				response_headers[h[0]] = h[1]
			response_headers[':status'] = event["status"]
			encoded_headers = self.header_encoder.encode(HeadersFrame.normalize_header_fields(response_headers))
			
			if len(encoded_headers) <= self.connection_settings.max_frame_size:
				self.response_queue.put(
					headers_frame.write(
						self.stream_id,
						flags={
							'end_stream': '0', 'end_headers': '1', 'padded': '0', 'priority': '1'
						},
						headers_block_fragment=encoded_headers[0:self.connection_settings.max_frame_size]
					)
				)	
			else:
				self.response_queue.put(
					headers_frame.write(
						self.stream_id,
						flags={
							'end_stream': '0', 'end_headers': '0', 'padded': '0', 'priority': '1'
						},
						headers_block_fragment=encoded_headers[0:self.connection_settings.max_frame_size]
					)
				)
			
				for chunk, is_last in utils.get_chunks(
					encoded_headers,
					self.connection_settings.max_frame_size,
					offset=self.connection_settings.max_frame_size
				):
					self.response_queue.put(
						ContinuationFrame().write(
							self.stream_id,
							flags={
								'end_stream': '0', 'end_headers': '1' if is_last else '0', 'padded': '0', 'priority': '1'
							},
							headers_block_fragment=chunk
						)
					)
		elif event["type"] == "http.response.body":
			if event["body"]:
				data_frame = DataFrame(self.connection_settings)
				try:
					for chunk, is_last in utils.get_chunks(event["body"], self.connection_settings.max_frame_size):
						self.response_queue.put(
							data_frame.write(
								self.stream_id,
								flags={'end_stream': '1' if is_last and not event["more_body"] else '0', 'padded': '0'},
								body=chunk
							)
						)
				except OSError as e:
					print(e)
			
			while not self.response_queue.empty():
				self.client_connection.sendall(self.response_queue.get().bytes)
		else:
			raise ValueError("Unkown event type: %s" % event["type"])