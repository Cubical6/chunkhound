<?php
use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration {
    public function up(): void {
        // A membership has an independent id and a unique team/user pair.
        // Defaults affect no structural constraint.
        // The schema call starts on line 12, as in spec §5.9.

        Schema::create('team_user', function (Blueprint $table) {
            $table->id();
            $table->foreignId('team_id')->constrained('teams');
            $table->foreignId('user_id')->constrained('users');
            $table->enum('role', ['member', 'lead'])->default('member');
            $table->unique(['team_id', 'user_id']);
        });
    }
};
