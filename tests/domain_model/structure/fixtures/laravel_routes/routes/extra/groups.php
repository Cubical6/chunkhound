<?php
use Illuminate\Support\Facades\Route;
use App\Http\Controllers\TeamMemberController;
Route::group(['prefix' => 'admin', 'controller' => TeamMemberController::class], function () {
    Route::get('users', 'index');
});
Route::prefix('/v1/')->group(['prefix' => '/admin/', 'controller' => TeamMemberController::class], fn () => Route::get('/users/', 'index'));
Route::prefix('/')->group(fn () => Route::get('/', fn () => null));
Route::get('teams', fn () => null);
Route::get('/teams/', fn () => null);
Route::prefix('teams')->group(fn () => Route::get('/', fn () => null));
Route::group(['prefix' => $prefix], fn () => Route::get('/unknown-prefix', fn () => null));
Route::group(['controller' => $controller], fn () => Route::get('/unknown-controller', 'index'));
collect(['x'])->each(fn () => Route::get('/each', fn () => null));
collect(['x'])->map(fn () => Route::get('/map', fn () => null));
array_map(fn () => Route::get('/array-map', fn () => null), ['x']);
array_walk($items, function () { Route::get('/array-walk', fn () => null); });
Route::get('/trait', [TeamMemberController::class, 'fromTrait']);
Route::get('/teams', fn () => null);
Route::get('', fn () => null);
