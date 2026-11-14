import { Controller, Get, Post, Patch, Delete, Body } from '@nestjs/common';
import { CreateTeamDto } from './team.dto';
import { Team } from './team.entity';

@Controller('teams')
export class TeamsController {
  @Get(':id')
  show(team: Team) { return team; }

  @Post()
  create(@Body() input: CreateTeamDto, team: Team) { return team; }

  @Patch(':id')
  update(@Body('team') input: CreateTeamDto) { return input; }

  @Delete(':id')
  remove() {}
}
