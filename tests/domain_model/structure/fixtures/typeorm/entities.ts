import { Role } from './role';

@Entity()
export class TeamRecord {
  @PrimaryGeneratedColumn() id: number;
  @Column({ type: 'varchar', length: 80 }) title: string;
}

@Entity('team_user')
@Unique(['team', 'email'], { deferrable: dynamicSetting })
@Unique('member_role', ['id', 'role'])
@Index(['email', 'role'], { unique: true })
export class TeamMember {
  @PrimaryColumn({ name: 'member_id', type: 'int' }) id: number;
  @ManyToOne(() => TeamRecord, { nullable: false })
  @JoinColumn({ name: 'team_id' }) team: TeamRecord;
  @Column({ type: 'varchar', name: 'email_address', unique: true }) email: string;
  @Column({ type: 'enum', enum: Role }) role: Role;
  @CreateDateColumn() createdAt: Date;
  @UpdateDateColumn() updatedAt: Date;
  @DeleteDateColumn({ nullable: true }) deletedAt: Date;
  @Column({ nullable: true }) owner_id: number;
  @VersionColumn() version: number;
  @Column() team_id: number;
  @ManyToOne(() => TeamRecord, { nullable: false })
  @JoinColumn({ name: 'owner_id' }) owner: TeamRecord;
  @OneToMany(() => TeamRecord, t => t.members) ignored: TeamRecord[];
  @ManyToMany(() => TeamRecord) @JoinTable() alsoIgnored: TeamRecord[];
}

@Entity({ name: 'migrations' })
export class MigrationRecord {
  @PrimaryGeneratedColumn() id: number;
  @Column({ type: 'varchar', length: dynamicLength }) description: string;
}
