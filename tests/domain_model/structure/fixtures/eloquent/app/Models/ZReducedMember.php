<?php
namespace App\Models;
use Example\Enums\ReducedStatus;
class ZReducedMember extends BaseRecord {
    protected $table = 'team_user';
    protected $casts = ['status' => ReducedStatus::class];
}
