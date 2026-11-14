<?php
return new class extends Migration {
    public function up(): void {
        Schema::table('team_user', function ($table) {
            $table->renameColumn('label', 'title');
        });
    }
};
