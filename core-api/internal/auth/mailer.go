package auth

import (
	"context"
	"crypto/tls"
	"fmt"
	"net"
	"net/mail"
	"net/smtp"
	"strings"
	"time"
)

type Mailer struct{ Host, Port, Username, Password, From string }

func (m Mailer) SendCode(ctx context.Context, email, purpose, code string) error {
	from, err := mail.ParseAddress(m.From)
	if err != nil {
		return err
	}
	to, err := mail.ParseAddress(email)
	if err != nil {
		return err
	}
	connection, err := (&net.Dialer{Timeout: 5 * time.Second}).DialContext(ctx, "tcp", net.JoinHostPort(m.Host, m.Port))
	if err != nil {
		return err
	}
	defer connection.Close()
	connection.SetDeadline(time.Now().Add(8 * time.Second))
	client, err := smtp.NewClient(connection, m.Host)
	if err != nil {
		return err
	}
	defer client.Close()
	if ok, _ := client.Extension("STARTTLS"); ok {
		if err = client.StartTLS(&tls.Config{ServerName: m.Host, MinVersion: tls.VersionTLS12}); err != nil {
			return err
		}
	}
	if m.Username != "" {
		if err = client.Auth(smtp.PlainAuth("", m.Username, m.Password, m.Host)); err != nil {
			return err
		}
	}
	if err = client.Mail(from.Address); err != nil {
		return err
	}
	if err = client.Rcpt(to.Address); err != nil {
		return err
	}
	w, err := client.Data()
	if err != nil {
		return err
	}
	subject := "Verify your AuraFind email"
	if purpose == "reset_password" {
		subject = "Reset your AuraFind password"
	}
	message := fmt.Sprintf("From: %s\r\nTo: %s\r\nSubject: %s\r\nMIME-Version: 1.0\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\nYour AuraFind code is %s\r\n\r\nThis code expires in 10 minutes. If you did not request it, you can ignore this email.\r\n", from.String(), to.String(), subject, code)
	if _, err = w.Write([]byte(strings.ReplaceAll(message, "\x00", ""))); err != nil {
		return err
	}
	if err = w.Close(); err != nil {
		return err
	}
	return client.Quit()
}
