-- First admin must be inserted into db, adds all others.
-- Replace 'EDITHERE' with your discord ID, obtainable by \@DiscordUsername
insert into admins (id, date) VALUES ("EDITHERE", NOW());

-- Size of databases, MB
-- SELECT table_schema AS "Database", SUM(data_length + index_length) / 1024 / 1024 AS "Size (MB)" FROM information_schema.TABLES GROUP BY table_schema;
