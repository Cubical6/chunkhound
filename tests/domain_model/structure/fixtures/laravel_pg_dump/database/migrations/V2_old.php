<?php
return new class extends Migration {
    public function up(): void {
        Schema::table('users', fn ($t) => $t->string('already_pruned'));
    }
};
