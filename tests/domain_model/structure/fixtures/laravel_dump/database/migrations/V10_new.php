<?php
return new class extends Migration {
    public function up(): void {
        Schema::table('notes', function ($table) { $table->string('title', 100); });
    }
};
