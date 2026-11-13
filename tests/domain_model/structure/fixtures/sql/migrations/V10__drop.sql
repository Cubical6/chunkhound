ALTER TABLE team_user ADD CONSTRAINT uq_title UNIQUE (title);
ALTER TABLE team_user DROP INDEX uq_user;
DROP INDEX uq_title;
