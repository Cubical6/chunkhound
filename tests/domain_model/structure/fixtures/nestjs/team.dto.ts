import { IsEmail, Length, IsEnum, ValidateNested, IsString } from 'class-validator';
import { Type } from 'class-transformer';
import { Status } from './status';

export class BaseDto {
  @IsString()
  label: string;
}
export class AddressDto {
  @IsString()
  city: string;
}
export class CreateTeamDto extends BaseDto {
  @Length(1, 20)
  @IsEmail()
  email: string;

  @IsEnum(Status)
  status: Status;

  @ValidateNested()
  @Type(() => AddressDto)
  address: AddressDto;
}
