CREATE TABLE teams (id BIGINT PRIMARY KEY);
CREATE TABLE team_user (
    id BIGINT PRIMARY KEY,
    team_id BIGINT NOT NULL,
    status ENUM('active', 'pending') NOT NULL,
    visibility VARCHAR(30),
    FOREIGN KEY (team_id) REFERENCES teams(id)
);
