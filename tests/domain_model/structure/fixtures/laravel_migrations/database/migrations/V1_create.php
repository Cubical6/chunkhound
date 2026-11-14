<?php
return new class extends Migration {
    public function up(): void {
        Schema::create('teams', function ($table) { $table->id(); });
        Schema::create('users', function ($table) { $table->id(); });
        Schema::create('team_user', function ($table) {
            $table->id();
            $table->foreignId('team_id')->constrained('teams');
            $table->foreignId('user_id')->constrained();
            $table->enum('role', ['member', 'lead'])->default('member');
            $table->unique(['team_id', 'user_id']);
        });
        Schema::create('jobs', function ($table) { $table->id(); });
        Schema::create('sessions', function ($table) { $table->string('id')->primary(); });
    }
    public function down(): void { Schema::drop('team_user'); }
};
