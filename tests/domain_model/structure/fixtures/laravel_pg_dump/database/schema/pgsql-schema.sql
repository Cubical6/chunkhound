CREATE TABLE public.users (id bigint NOT NULL, name character varying(255));
ALTER TABLE ONLY public.users ADD CONSTRAINT users_pkey PRIMARY KEY (id);
CREATE TABLE public.migrations (id integer NOT NULL, migration character varying(255), batch integer);
COPY public.migrations (batch, migration, id) FROM stdin;
1	V1_users	1
1	V2_old	2
\.
CREATE TABLE public.payloads (content text);
COPY public.payloads (content) FROM stdin;
ALTER TABLE public.users ADD COLUMN garbage text;
\.
ALTER TABLE public.users ADD COLUMN code character(10);
