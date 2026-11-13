CREATE TABLE ordered_keys (
  UNIQUE (second),
  first text UNIQUE,
  second text
);
CREATE TABLE ordered_references (
  id int PRIMARY KEY,
  FOREIGN KEY (owner_id) REFERENCES users(id),
  owner_id bigint REFERENCES teams(id)
);
CREATE TABLE literal_values (
  id int PRIMARY KEY,
  label enum('busy, now', 'With (spaces)', 'can''t') DEFAULT 'busy, now',
  count int NOT NULL DEFAULT (NULL),
  owner_id int NOT NULL REFERENCES users(id) ON DELETE SET NULL,
  other_id int,
  CHECK (count > other_id)
);
CREATE TABLE pair_target (
  first_id int,
  second_id int,
  PRIMARY KEY (first_id, second_id)
);
CREATE TABLE pair_link (
  left_id int NOT NULL,
  right_id int NOT NULL,
  FOREIGN KEY (left_id, right_id) REFERENCES pair_target(first_id, second_id)
);
