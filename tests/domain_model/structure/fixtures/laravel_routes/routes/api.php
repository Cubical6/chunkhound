<?php
use Illuminate\Support\Facades\Route;
use App\Http\Controllers\TeamMemberController;
Route::middleware('auth')->prefix('teams')->group(function () {
    Route::prefix('{team}')->group(function () {
        Route::controller(TeamMemberController::class)->group(function () {
            Route::post('members', 'store');
            Route::get('members', 'index');
        });
    });
});
Route::get('/health', fn () => 'ok');
Route::head('/health', function () {});
Route::post('/literal', 'App\Http\Controllers\TeamMemberController@store');
Route::put('/members/{member}', [TeamMemberController::class, 'update']);
Route::patch('/members/{member}', [TeamMemberController::class, 'update']);
Route::delete('/members/{member}', [TeamMemberController::class, 'destroy']);
Route::options('/options', function () {});
Route::match(['get', 'post'], '/matched', function () {});
Route::any('/anything', function () {});
Route::get('/invoke', TeamMemberController::class);
Route::get('/missing', [MissingController::class, 'show']);
Route::get('/missing-method', [TeamMemberController::class, 'absent']);
Route::get('/duplicate', [TeamMemberController::class, 'index']);
Route::get('/duplicate', [TeamMemberController::class, 'store']);
Route::apiResource('/notes', TeamMemberController::class)->only(['index', 'show']);
Route::resource('/teams', TeamMemberController::class)->except(['destroy']);
Route::view('/welcome', 'welcome');
Route::redirect('/old', '/new');
foreach (['a', 'b'] as $name) {
    Route::get('/loop', [TeamMemberController::class, 'index']);
}
Route::get($path, [TeamMemberController::class, 'index']);
Route::get('/dynamic-handler', $handler);
for ($i = 0; $i < 1; $i++) { Route::get('/for', fn () => null); }
while ($flag) { Route::get('/while', fn () => null); }
Route::get('/invoke-string', 'App\Http\Controllers\TeamMemberController');
Route::match('get', '/match-string', ['uses' => 'App\Http\Controllers\TeamMemberController@index']);
Route::get('/legacy', ['uses' => 'App\Http\Controllers\TeamMemberController@index', 'as' => 'legacy']);
