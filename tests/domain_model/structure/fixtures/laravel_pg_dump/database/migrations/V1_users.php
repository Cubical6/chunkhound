<?php
return new class extends Migration {
    public function up(): void { Schema::create('users', fn ($t) => $t->id()); }
};
