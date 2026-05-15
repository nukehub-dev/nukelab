import { useQuery, useMutation } from '@tanstack/react-query';
import { api } from '../lib/api';

export interface EmailConfig {
  smtp_host: string;
  smtp_port: number;
  smtp_user: string;
  smtp_from: string;
  smtp_from_name: string;
  smtp_tls: boolean;
  smtp_verify_certs: boolean;
  enabled: boolean;
  password_configured: boolean;
}

export interface EmailStatus {
  status: 'connected' | 'error' | 'disabled';
  message: string;
  configured: boolean;
  host?: string;
  port?: number;
}

export interface EmailTestResponse {
  success: boolean;
  message: string;
  recipient: string;
}

export function useEmailConfig() {
  return useQuery({
    queryKey: ['admin', 'email-config'],
    queryFn: async () => {
      const response = await api.get<EmailConfig>('/admin/email-config');
      return response;
    },
    refetchOnMount: true,
    refetchOnWindowFocus: true,
  });
}

export function useEmailStatus() {
  return useQuery({
    queryKey: ['admin', 'email-status'],
    queryFn: async () => {
      const response = await api.get<EmailStatus>('/admin/email-status');
      return response;
    },
    refetchInterval: 30000,
    refetchOnMount: true,
    refetchOnWindowFocus: true,
  });
}

export function useEmailTest() {
  return useMutation({
    mutationFn: async (toEmail?: string) => {
      const response = await api.post<EmailTestResponse>('/admin/email-test', {
        to_email: toEmail || null,
      });
      return response;
    },
  });
}
