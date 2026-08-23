# Incremental NMEA extraction from the raw receiver stream.
#
# The receiver mixes ASCII NMEA sentences with binary UBX frames on the same
# UART. The WebSocket carries text, so the binary has to be filtered out here -
# the static measurement logger takes the raw stream instead.

# Longest sane sentence is 82 bytes, the cap only guards against garbage
MAX_BUFFER = 4096


class Extractor:
    """Feeds raw chunks in, gets complete NMEA sentences out."""

    def __init__(self):
        self._buffer = bytearray()
        self.dropped_bytes = 0

    def feed(self, chunk: bytes) -> list:
        """Adds a chunk to the buffer and pulls out every finished sentence.

        Parameters:
            chunk (bytes): Raw bytes as they came from the port

        Returns:
            list: Complete sentences as strings, without the line ending
        """
        self._buffer.extend(chunk)

        sentences = []

        while True:
            # Anything before the next '$' is UBX or line noise
            start = self._buffer.find(b"$")
            if start < 0:
                self.dropped_bytes += len(self._buffer)
                self._buffer.clear()
                break

            if start > 0:
                self.dropped_bytes += start
                del self._buffer[:start]

            end = self._buffer.find(b"\n")
            if end < 0:
                # Sentence still incomplete, wait for the next chunk
                break

            line = bytes(self._buffer[:end])
            del self._buffer[:end + 1]

            sentence = line.decode("ascii", errors="ignore").strip()
            if sentence:
                sentences.append(sentence)

        # A '$' with no line ending in sight means the stream is not NMEA
        if len(self._buffer) > MAX_BUFFER:
            self.dropped_bytes += len(self._buffer)
            self._buffer.clear()

        return sentences
