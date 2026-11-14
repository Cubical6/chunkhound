<?php
return new class extends Migration {
    public function up(): void { Schema::create('notes', function ($table) { $table->id(); }); }
};
