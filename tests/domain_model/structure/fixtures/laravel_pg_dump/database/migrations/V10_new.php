<?php
return new class extends Migration {
    public function up(): void {
        Schema::connection('pgsql')->table('users', fn ($t) => $t->string('title', length: 50));
    }
};
