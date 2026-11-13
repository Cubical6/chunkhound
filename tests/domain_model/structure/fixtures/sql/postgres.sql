CREATE TYPE mood AS ENUM ('calm', 'busy');
CREATE TABLE notes (
  id integer PRIMARY KEY,
  user_id integer REFERENCES users(id),
  state text CHECK (state IN ('new', 'done')),
  feeling mood
);
ALTER TABLE notes UNRECOGNIZED state;
