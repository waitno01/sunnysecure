export type EmailEntry = {
  email: string;
  inbox_count: number;
  inbox: EmailMessage[];
};

export type EmailMessage = {
  id: number;
  to_address: string;
  from_address: string;
  subject: string;
  body: string;
  received_at: string;
};
