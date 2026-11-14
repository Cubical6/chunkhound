CREATE TABLE team_members (
  member_key INTEGER PRIMARY KEY,
  name VARCHAR(80) NOT NULL
);
CREATE TABLE composite_members (
  left_id INTEGER NOT NULL,
  right_id INTEGER NOT NULL,
  id INTEGER NOT NULL,
  PRIMARY KEY (left_id, right_id)
);
