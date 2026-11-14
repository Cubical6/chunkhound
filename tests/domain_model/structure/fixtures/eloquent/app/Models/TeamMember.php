<?php
namespace App\Models;
use Example\Enums\{Status as MemberStatus, Visibility};
class TeamMember extends BaseRecord {
    protected $table = 'team_user';
    protected $casts = ['status' => MemberStatus::class];
    protected function casts(): array {
        return ['visibility' => Visibility::class];
    }
    public function team() { return $this->belongsTo(Team::class); }
    public function user() { return $this->belongsTo(User::class, 'user_id'); }
    public function ignored() { return $this->hasMany(User::class); }
}
