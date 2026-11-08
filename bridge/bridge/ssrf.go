package bridge

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"strings"
	"syscall"
	"time"
)

var (
	errDisallowedURL       = errors.New("disallowed external URL")
	errDisallowedIPAddress = errors.New("refusing connection to non-public IP address")
	cgnatPrefix            = netip.MustParsePrefix("100.64.0.0/10")
	benchmarkPrefix        = netip.MustParsePrefix("198.18.0.0/15")
)

var allowedInstagramMediaHosts = []string{
	"instagram.com",
	"cdninstagram.com",
	"fbcdn.net",
	"fbsbx.com",
}

func isPublicNetipAddr(addr netip.Addr) bool {
	unmapped := addr.Unmap()
	if !unmapped.IsValid() || !unmapped.IsGlobalUnicast() {
		return false
	}
	if unmapped.IsPrivate() ||
		unmapped.IsLoopback() ||
		unmapped.IsLinkLocalUnicast() ||
		unmapped.IsLinkLocalMulticast() ||
		unmapped.IsMulticast() ||
		unmapped.IsUnspecified() ||
		unmapped.IsInterfaceLocalMulticast() {
		return false
	}
	if cgnatPrefix.Contains(unmapped) || benchmarkPrefix.Contains(unmapped) {
		return false
	}
	return true
}

func validatePublicHost(hostname string) error {
	clean := strings.ToLower(strings.TrimSuffix(strings.TrimSpace(hostname), "."))
	if clean == "" {
		return fmt.Errorf("%w: missing host", errDisallowedURL)
	}
	if clean == "localhost" || strings.HasSuffix(clean, ".localhost") || strings.HasSuffix(clean, ".local") || strings.HasSuffix(clean, ".internal") {
		return fmt.Errorf("%w: local hostname %q is not permitted", errDisallowedURL, clean)
	}
	if addr, err := netip.ParseAddr(clean); err == nil {
		if !isPublicNetipAddr(addr) {
			return fmt.Errorf("%w: %s", errDisallowedIPAddress, clean)
		}
	}
	return nil
}

func validateExternalURL(rawURL string, requireHTTPS bool, allowedHosts []string) (*url.URL, error) {
	parsed, err := url.Parse(strings.TrimSpace(rawURL))
	if err != nil {
		return nil, fmt.Errorf("%w: %v", errDisallowedURL, err)
	}
	scheme := strings.ToLower(parsed.Scheme)
	if requireHTTPS {
		if scheme != "https" {
			return nil, fmt.Errorf("%w: HTTPS is required", errDisallowedURL)
		}
	} else if scheme != "http" && scheme != "https" {
		return nil, fmt.Errorf("%w: only http/https schemes are allowed", errDisallowedURL)
	}
	if parsed.User != nil {
		return nil, fmt.Errorf("%w: embedded credentials are not allowed", errDisallowedURL)
	}
	host := parsed.Hostname()
	if err := validatePublicHost(host); err != nil {
		return nil, err
	}
	if port := parsed.Port(); port != "" {
		if scheme == "https" && port != "443" {
			if len(allowedHosts) > 0 {
				return nil, fmt.Errorf("%w: disallowed HTTPS port %s", errDisallowedURL, port)
			}
		}
		if scheme == "http" && port != "80" && len(allowedHosts) > 0 {
			return nil, fmt.Errorf("%w: disallowed HTTP port %s", errDisallowedURL, port)
		}
	}
	if len(allowedHosts) > 0 {
		lowerHost := strings.ToLower(strings.TrimSuffix(host, "."))
		matched := false
		for _, allowed := range allowedHosts {
			if lowerHost == allowed || strings.HasSuffix(lowerHost, "."+allowed) {
				matched = true
				break
			}
		}
		if !matched {
			return nil, fmt.Errorf("media host is not trusted: %s", lowerHost)
		}
	}
	return parsed, nil
}

func validateMediaURL(rawURL string) (*url.URL, error) {
	return validateExternalURL(rawURL, true, allowedInstagramMediaHosts)
}

func safeDialControl(_ string, address string, _ syscall.RawConn) error {
	host, _, err := net.SplitHostPort(address)
	if err != nil {
		host = address
	}
	addr, err := netip.ParseAddr(host)
	if err != nil {
		return fmt.Errorf("%w: unresolved dial address", errDisallowedIPAddress)
	}
	if !isPublicNetipAddr(addr) {
		return fmt.Errorf("%w: %s", errDisallowedIPAddress, addr.String())
	}
	return nil
}

func newSafeHTTPClient(timeout time.Duration, requireHTTPS bool, allowedHosts []string) *http.Client {
	dialer := &net.Dialer{
		Timeout:   10 * time.Second,
		KeepAlive: 30 * time.Second,
		Control:   safeDialControl,
	}
	transport := &http.Transport{
		Proxy:               nil, // Do not let proxy environment variables bypass dial IP checks.
		DialContext:         func(ctx context.Context, network, addr string) (net.Conn, error) { return dialer.DialContext(ctx, network, addr) },
		ForceAttemptHTTP2:   true,
		MaxIdleConns:        10,
		IdleConnTimeout:     30 * time.Second,
		TLSHandshakeTimeout: 10 * time.Second,
	}
	return &http.Client{
		Timeout:   timeout,
		Transport: transport,
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			if len(via) >= 5 {
				return errors.New("too many redirects")
			}
			_, err := validateExternalURL(req.URL.String(), requireHTTPS, allowedHosts)
			return err
		},
	}
}

