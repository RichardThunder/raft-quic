package transport

import (
	"encoding/binary"
	"fmt"
	"io"
)

// RPC type bytes in the wire frame.
const (
	rpcAppendEntries   byte = 0x01
	rpcRequestVote     byte = 0x02
	rpcInstallSnapshot byte = 0x03
	rpcTimeoutNow      byte = 0x04
)

// maxFrameSize guards against rogue large allocations (64 MiB).
const maxFrameSize = 64 << 20

// writeFrame writes a length-prefixed frame:
//
//	[1 byte rpcType] [4 bytes big-endian length] [length bytes body]
func writeFrame(w io.Writer, rpcType byte, body []byte) error {
	if len(body) > maxFrameSize {
		return fmt.Errorf("frame body too large: %d bytes", len(body))
	}
	hdr := [5]byte{rpcType}
	binary.BigEndian.PutUint32(hdr[1:], uint32(len(body)))
	if _, err := w.Write(hdr[:]); err != nil {
		return err
	}
	if len(body) > 0 {
		_, err := w.Write(body)
		return err
	}
	return nil
}

// readFrame reads a frame written by writeFrame.
// It returns the rpcType and the body bytes.
func readFrame(r io.Reader) (rpcType byte, body []byte, err error) {
	var hdr [5]byte
	if _, err = io.ReadFull(r, hdr[:]); err != nil {
		return 0, nil, err
	}
	rpcType = hdr[0]
	length := binary.BigEndian.Uint32(hdr[1:])
	if length > maxFrameSize {
		return 0, nil, fmt.Errorf("frame length %d exceeds max %d", length, maxFrameSize)
	}
	if length == 0 {
		return rpcType, nil, nil
	}
	body = make([]byte, length)
	_, err = io.ReadFull(r, body)
	return rpcType, body, err
}
