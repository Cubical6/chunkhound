<?php
use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;
return new class extends Migration {
    public function up(): void {
        Schema::create('squads', function (Blueprint $table) {
            $table->id();
        });
        Schema::create('users', function (Blueprint $table) {
            $table->id();
        });
        Schema::create('team_user', function (Blueprint $table) {
            $table->id();
            $table->foreignId('team_id')->constrained('squads');
            $table->foreignId('user_id')->constrained();
            $table->enum('status', ['active', 'pending']);
            $table->string('visibility');
        });
        Schema::create('people', function (Blueprint $table) {
            $table->id();
        });
        Schema::create('audit_log', function (Blueprint $table) {
            $table->id();
        });
    }
};
