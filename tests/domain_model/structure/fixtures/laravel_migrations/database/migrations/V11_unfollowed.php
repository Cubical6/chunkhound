<?php
return new class extends Migration {
    public function up(): void {
        DB::statement('UPDATE team_user SET role = role');
        Schema::table('team_user', function ($table) {
            $table->mysteryType('not_a_column');
            $table->string($dynamicName);
        });
        if (Schema::hasColumn('users', 'name')) {
            Schema::table('users', function ($table) { $table->dropColumn('name'); });
        }
    }
};
