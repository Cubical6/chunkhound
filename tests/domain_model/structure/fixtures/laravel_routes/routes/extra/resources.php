<?php
use Illuminate\Support\Facades\Route;
use App\Http\Controllers\TeamMemberController;
Route::apiResource('/all', TeamMemberController::class);
Route::resource('/limited', TeamMemberController::class)->only('index', 'create');
Route::apiResource('/dynamic-only', TeamMemberController::class)->only($actions);
Route::resource('/dynamic-except', TeamMemberController::class)->except($actions);
Route::apiResource('/except', TeamMemberController::class)->except(['store', 'update']);
Route::apiResources([
    'houses' => TeamMemberController::class,
    'courses' => TeamMemberController::class,
    'expenses' => TeamMemberController::class,
    'purchases' => TeamMemberController::class,
    'licenses' => TeamMemberController::class,
    'movies' => TeamMemberController::class,
    'categories' => TeamMemberController::class,
    'boxes' => TeamMemberController::class,
    'churches' => TeamMemberController::class,
    'statuses' => TeamMemberController::class,
    'addresses' => TeamMemberController::class,
    'team-members' => TeamMemberController::class,
    'people' => TeamMemberController::class,
    'buses' => TeamMemberController::class,
    'glass' => TeamMemberController::class,
    'status' => TeamMemberController::class,
], ['only' => ['show']]);
Route::resources(['libraries' => TeamMemberController::class], ['only' => ['create', 'edit']]);
Route::resource('teams.team-members', TeamMemberController::class)->parameters(['teams' => 'group', 'team-members' => 'person'])->shallow();
Route::prefix('v1.0')->group(fn () => Route::apiResource('teams.team-members', TeamMemberController::class)->only(['index', 'show']));
