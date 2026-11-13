CREATE TABLE `team_user` (
  `id` bigint PRIMARY KEY,
  `user_id` bigint NOT NULL,
  `role` enum('member','lead'),
  UNIQUE KEY `uq_user` (`user_id`),
  CONSTRAINT `fk_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB;
CREATE TABLE flyway_schema_history (id bigint PRIMARY KEY);
