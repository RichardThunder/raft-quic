package transport

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"net"
	"time"
)

const alpnProto = "raft-quic/1"

// GenerateTLSConfig creates a self-signed certificate and returns
// server and client tls.Config values suitable for QUIC.
func GenerateTLSConfig() (serverTLS *tls.Config, clientTLS *tls.Config, err error) {
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, nil, err
	}

	template := &x509.Certificate{
		SerialNumber: big.NewInt(1),
		Subject:      pkix.Name{Organization: []string{"raft-quic"}},
		IPAddresses:  []net.IP{net.ParseIP("127.0.0.1"), net.ParseIP("::1")},
		NotBefore:    time.Now().Add(-time.Minute),
		NotAfter:     time.Now().Add(24 * time.Hour * 365),
		KeyUsage:     x509.KeyUsageDigitalSignature,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth, x509.ExtKeyUsageClientAuth},
	}

	certDER, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		return nil, nil, err
	}

	keyDER, err := x509.MarshalECPrivateKey(key)
	if err != nil {
		return nil, nil, err
	}

	cert, err := tls.X509KeyPair(
		pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: certDER}),
		pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: keyDER}),
	)
	if err != nil {
		return nil, nil, err
	}

	certPool := x509.NewCertPool()
	leafCert, err := x509.ParseCertificate(certDER)
	if err != nil {
		return nil, nil, err
	}
	certPool.AddCert(leafCert)

	serverTLS = &tls.Config{
		Certificates: []tls.Certificate{cert},
		NextProtos:   []string{alpnProto},
		ClientAuth:   tls.RequireAnyClientCert,
	}

	clientTLS = &tls.Config{
		Certificates:       []tls.Certificate{cert},
		RootCAs:            certPool,
		InsecureSkipVerify: true, // self-signed, PoC only
		NextProtos:         []string{alpnProto},
	}

	return serverTLS, clientTLS, nil
}
