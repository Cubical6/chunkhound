-- Values retain spelling, commas and SQL-escaped quotes.
CREATE TYPE public.mood AS ENUM ('calm', 'busy, now', 'can''t');
CREATE TABLE public.invoice (
  note text,
  id integer PRIMARY KEY,
  user_id bigint REFERENCES public.users,
  mood public.mood NOT NULL,
  size varchar(8) CHECK (size IN ('small', 'large')),
  amount NUMERIC(12, 4) NOT NULL,
  CONSTRAINT positive_amount CHECK (amount > 0),
  CHECK (amount < 100),
  CONSTRAINT bounded CHECK (amount > id)
);
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS invoice_note ON public.invoice USING btree (note);
CREATE UNIQUE INDEX IF NOT EXISTS invoice_note ON public.invoice USING btree (note);
CREATE TABLE public.inline_checks (
  id int PRIMARY KEY,
  state text CONSTRAINT allowed_state CHECK (state IN ('new', 'done')),
  score int CHECK (score >= 0),
  code text UNIQUE,
  description text DEFAULT 'PRIMARY KEY, NOT NULL',
  user_id bigint,
  audit_note text REFERENCES audit_line,
  FOREIGN KEY (user_id) REFERENCES public.users
);
CREATE INDEX ignored_index ON invoice (amount);
INSERT INTO invoice (id, note) VALUES (1, 'not schema');
