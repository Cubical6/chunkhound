import { Resolver, Mutation, Query, Subscription, ResolveField, Args } from '@nestjs/graphql';
import { CreateTeamDto } from './team.dto';

@Resolver()
export class TeamsResolver {
  @Mutation('addTeam')
  add(@Args('input') input: CreateTeamDto) { return true; }
}

@Resolver(() => String)
export class CodeFirstResolver {
  @Query({ name: 'teamCount' })
  count() { return 0; }

  @Subscription()
  teamChanged() {}

  @ResolveField()
  ignored() {}
}
