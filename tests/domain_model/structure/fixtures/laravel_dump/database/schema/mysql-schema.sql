CREATE TABLE `users` (`id` bigint NOT NULL, PRIMARY KEY (`id`)) ENGINE=InnoDB;
CREATE TABLE `notes` (`id` bigint NOT NULL, `user_id` bigint NOT NULL, PRIMARY KEY (`id`)) ENGINE=InnoDB;
ALTER TABLE `notes` ADD CONSTRAINT `notes_user_id_foreign` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
CREATE TABLE `migrations` (`id` int NOT NULL, `migration` varchar(255) NOT NULL, `batch` int NOT NULL, PRIMARY KEY (`id`));
INSERT INTO `migrations` (`id`, `migration`, `batch`) VALUES (1, 'V1_users', 1);
INSERT INTO `migrations` VALUES (2, 'V2_notes', 1);
INSERT INTO `migrations` (`migration`, `batch`, `id`) VALUES ('V3_old', 1, 3);
