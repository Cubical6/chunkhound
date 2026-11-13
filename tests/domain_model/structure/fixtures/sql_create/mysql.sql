CREATE TABLE `users` (
  `email` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `id` bigint unsigned NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `users_email` (`email`)
) ENGINE=InnoDB;
CREATE TABLE `teams` (`id` bigint PRIMARY KEY);
CREATE TABLE `team_user` (
  `id` bigint PRIMARY KEY,
  `team_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `role` enum('member','lead') NULL,
  CONSTRAINT `fk_team` FOREIGN KEY (`team_id`) REFERENCES `teams` (`id`),
  CONSTRAINT `fk_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
  UNIQUE KEY `team_member` (`team_id`, `user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE `team_link` (
  `team_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  PRIMARY KEY (`team_id`, `user_id`),
  FOREIGN KEY (`team_id`) REFERENCES `teams` (`id`),
  FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
);
CREATE TABLE `audit_line` (`note` text);
CREATE TABLE `external_note` (
  `id` int PRIMARY KEY,
  `remote_id` int REFERENCES `remote_users` (`id`)
);
CREATE TABLE `ambiguous` (
  `id` int PRIMARY KEY,
  `owner_id` bigint,
  CONSTRAINT `first_owner` FOREIGN KEY (`owner_id`) REFERENCES `users` (`id`),
  CONSTRAINT `second_owner` FOREIGN KEY (`owner_id`) REFERENCES `teams` (`id`)
);
CREATE TABLE `unique_only` (`code` varchar(8) CHARSET utf8mb4, `note` text, UNIQUE (`code`));
CREATE TABLE IF NOT EXISTS `users` (`ignored` int);
CREATE TABLE search_data (body text, location geometry,
  FULLTEXT KEY body_search (body), SPATIAL KEY location_key (location),
  SPATIAL INDEX location_index (location));
